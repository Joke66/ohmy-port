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

    /// <summary>
    /// 曲线渲染冒烟（命令行 --plot-smoke 触发）：灌两路合成数据，把画布渲染成 PNG。
    /// 用于无硬件时验证 PlotCanvas 的绘制 / 缩放 / 断线逻辑。
    /// </summary>
    public static void RunPlotSmoke()
    {
        var hub = new OhmyPort.Core.Models.PlotHub();
        hub.Configure(
        [
            new OhmyPort.Core.Models.PlotRuleConfig("正弦", "sin="),
            new OhmyPort.Core.Models.PlotRuleConfig("方波", "step="),
        ], 600);

        for (var i = 0; i < 600; i++)
        {
            var sin = Math.Sin(i / 40.0) * 25 + 50;
            // 每 150 点故意缺一次采样，验证断线
            var step = i % 150 == 0 ? "step=none" : $"step={(i % 100 < 50 ? 10 : 80)}";
            hub.Feed($"sin={sin:F2} {step}");
        }

        const int width = 820;
        const int height = 460;
        var canvas = new Controls.PlotCanvas { Hub = hub };
        var window = new Window
        {
            Width = width,
            Height = height,
            WindowStyle = WindowStyle.None,
            ShowInTaskbar = false,
            Content = canvas,
        };
        ThemeService.AttachWindow(window);
        window.Show();
        window.UpdateLayout();
        canvas.InvalidateVisual();
        window.UpdateLayout();

        // 按画布实际尺寸渲染（窗口非客户区会让 ActualWidth/Height 小于窗口尺寸）
        var pixelWidth = (int)Math.Round(canvas.ActualWidth);
        var pixelHeight = (int)Math.Round(canvas.ActualHeight);

        var bitmap = new System.Windows.Media.Imaging.RenderTargetBitmap(
            pixelWidth, pixelHeight, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
        bitmap.Render(canvas);

        var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder();
        encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
        var path = System.IO.Path.Combine(AppContext.BaseDirectory, "plot_smoke.png");
        using (var stream = File.Create(path))
        {
            encoder.Save(stream);
        }

        window.Close();
        Application.Current.Shutdown();
    }
}
