using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows;
using OhmyPort.App.Controls;

namespace OhmyPort.App;

/// <summary>
/// 日志控件性能压测（命令行 --stress 触发）：
/// 验证 AvalonEdit 在 5 万行上限下的追加 / 裁剪 / 实时追加 / 滚底性能。
/// </summary>
public static class StressTest
{
    public static void Run()
    {
        var result = new StringBuilder();
        var window = new Window
        {
            Width = 1000,
            Height = 700,
            ShowInTaskbar = false,
        };
        var log = new LogView();
        window.Content = log;
        window.Show();

        var line = (int i) =>
            $"[12:00:00.000] [00:00:{i / 1000:D2}.{i % 1000:D3}] alive tick={i} clk=48000000 Hz";

        // 1) 一次性灌 5 万行
        var all = Enumerable.Range(0, 50_000).Select(line).ToList();
        var sw = Stopwatch.StartNew();
        log.AppendLines(all, follow: true);
        sw.Stop();
        window.UpdateLayout();
        result.AppendLine($"append_50000_lines_ms={sw.ElapsedMilliseconds}");
        result.AppendLine($"line_count_after_append={log.LineCount}");

        // 2) 再灌 5 万行（触发 MaxLines 裁剪，总行数应稳定在 50000 附近）
        sw.Restart();
        log.AppendLines(all, follow: true);
        sw.Stop();
        window.UpdateLayout();
        result.AppendLine($"append_another_50000_ms={sw.ElapsedMilliseconds}");
        result.AppendLine($"line_count_after_trim={log.LineCount}");

        // 3) 分批实时追加（模拟 80ms 一批，每批约 40 行，共 200 批）
        var batch = Enumerable.Range(0, 40)
            .Select(i => $"[12:00:00.000] batch tick={i}").ToList();
        var totalBatch = 0L;
        var maxBatch = 0L;
        for (var i = 0; i < 200; i++)
        {
            sw.Restart();
            log.AppendLines(batch, follow: true);
            sw.Stop();
            totalBatch += sw.ElapsedMilliseconds;
            if (sw.ElapsedMilliseconds > maxBatch)
            {
                maxBatch = sw.ElapsedMilliseconds;
            }
        }

        result.AppendLine($"batch_200_avg_ms={totalBatch / 200.0:F2}");
        result.AppendLine($"batch_200_max_ms={maxBatch}");
        result.AppendLine($"line_count_final={log.LineCount}");

        // 4) 滚到底
        sw.Restart();
        log.ScrollToEnd();
        window.UpdateLayout();
        sw.Stop();
        result.AppendLine($"scroll_to_end_ms={sw.ElapsedMilliseconds}");

        // 5) 全文档文本提取（保存/复制路径的参考）
        sw.Restart();
        var textLength = log.Document.TextLength;
        sw.Stop();
        result.AppendLine($"text_length={textLength}");

        var path = System.IO.Path.Combine(AppContext.BaseDirectory, "stress_result.txt");
        File.WriteAllText(path, result.ToString());
        window.Close();
        Application.Current.Shutdown();
    }
}
