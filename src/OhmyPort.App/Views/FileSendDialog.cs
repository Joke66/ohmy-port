using System.IO;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using OhmyPort.Core;

namespace OhmyPort.App.Views;

/// <summary>
/// 文件发送（下发）对话框：选文件 → 按格式分块 → 后台线程逐块发送，支持分包大小 / 间隔 / 取消。
/// 三种格式：HEX 文本（解析成字节）、文本行（逐行 + 转义 + 换行）、二进制 raw（原始字节流）。
/// </summary>
public class FileSendDialog : Window
{
    private static readonly Encoding Utf8 = new UTF8Encoding(false);

    private readonly Func<byte[], bool> _send;
    private readonly TextBox _pathEdit = new();
    private readonly ComboBox _formatCombo = new();
    private readonly TextBox _chunkEdit = new();
    private readonly TextBox _intervalEdit = new();
    private readonly ComboBox _newlineCombo = new();
    private readonly ProgressBar _progress = new();
    private readonly TextBlock _status = new();
    private readonly Button _startButton = new();

    private CancellationTokenSource? _cts;
    private Thread? _thread;

    public FileSendDialog(Func<byte[], bool> send, string title)
    {
        _send = send;
        Title = $"文件发送 — {title}";
        Width = 560;
        Height = 400;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        ThemeService.AttachWindow(this);

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // 0 文件
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // 1 格式行
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // 2 分包行
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // 3 进度
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); // 4 状态
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // 5 按钮

        // 文件行
        var fileRow = new Grid { Margin = new Thickness(0, 0, 0, 10) };
        fileRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        fileRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        fileRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var fileLabel = new TextBlock { Text = "文件", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 8, 0) };
        Grid.SetColumn(fileLabel, 0);
        fileRow.Children.Add(fileLabel);

        _pathEdit.VerticalContentAlignment = VerticalAlignment.Center;
        _pathEdit.MinHeight = 28;
        Grid.SetColumn(_pathEdit, 1);
        fileRow.Children.Add(_pathEdit);

        var browse = new Button { Content = "浏览...", Margin = new Thickness(8, 0, 0, 0) };
        browse.Click += (_, _) => Browse();
        Grid.SetColumn(browse, 2);
        fileRow.Children.Add(browse);

        Grid.SetRow(fileRow, 0);
        grid.Children.Add(fileRow);

        // 格式 + 换行
        var formatRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
        formatRow.Children.Add(new TextBlock { Text = "格式", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 6, 0) });
        _formatCombo.DisplayMemberPath = nameof(Option.Label);
        _formatCombo.SelectedValuePath = nameof(Option.Value);
        _formatCombo.ItemsSource = new[]
        {
            new Option("HEX 文本", FileSendFormat.HexText),
            new Option("文本行", FileSendFormat.TextLines),
            new Option("二进制 raw", FileSendFormat.RawBinary),
        };
        _formatCombo.SelectedIndex = 0;
        _formatCombo.MinHeight = 28;
        _formatCombo.Width = 130;
        _formatCombo.SelectionChanged += (_, _) => UpdateNewlineVisibility();
        formatRow.Children.Add(_formatCombo);

        formatRow.Children.Add(new TextBlock { Text = "换行", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(16, 0, 6, 0) });
        _newlineCombo.DisplayMemberPath = nameof(Option.Label);
        _newlineCombo.SelectedValuePath = nameof(Option.Value);
        _newlineCombo.ItemsSource = SerialDefaults.Newlines.Select(n => new Option(n.Label, n.Value)).ToArray();
        _newlineCombo.SelectedIndex = 3; // \r\n
        _newlineCombo.MinHeight = 28;
        _newlineCombo.Width = 90;
        formatRow.Children.Add(_newlineCombo);

        Grid.SetRow(formatRow, 1);
        grid.Children.Add(formatRow);

        // 分包大小 + 间隔
        var chunkRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
        chunkRow.Children.Add(new TextBlock { Text = "分包大小(字节)", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 6, 0) });
        _chunkEdit.Text = "512";
        _chunkEdit.Width = 90;
        _chunkEdit.VerticalContentAlignment = VerticalAlignment.Center;
        chunkRow.Children.Add(_chunkEdit);

        chunkRow.Children.Add(new TextBlock { Text = "分包间隔(ms)", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(16, 0, 6, 0) });
        _intervalEdit.Text = "0";
        _intervalEdit.Width = 90;
        _intervalEdit.VerticalContentAlignment = VerticalAlignment.Center;
        chunkRow.Children.Add(_intervalEdit);

        Grid.SetRow(chunkRow, 2);
        grid.Children.Add(chunkRow);

        // 进度条
        _progress.Minimum = 0;
        _progress.Maximum = 1;
        _progress.Value = 0;
        _progress.Height = 6;
        _progress.Margin = new Thickness(0, 4, 0, 6);
        Grid.SetRow(_progress, 3);
        grid.Children.Add(_progress);

        // 状态文本
        _status.Text = "就绪（未连接或格式错误会在开始后提示）";
        _status.TextWrapping = TextWrapping.Wrap;
        _status.Foreground = (Brush)Application.Current.Resources["Brush.Muted"];
        _status.VerticalAlignment = VerticalAlignment.Top;
        Grid.SetRow(_status, 4);
        grid.Children.Add(_status);

        // 按钮
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 8, 0, 0) };
        _startButton.Content = "开始发送";
        _startButton.Tag = "accent";
        _startButton.Width = 100;
        _startButton.Margin = new Thickness(0, 0, 8, 0);
        _startButton.Click += (_, _) => ToggleSend();
        buttons.Children.Add(_startButton);

        var close = new Button { Content = "关闭", Width = 80 };
        close.Click += (_, _) => Close();
        buttons.Children.Add(close);

        Grid.SetRow(buttons, 5);
        grid.Children.Add(buttons);

        Content = grid;
        UpdateNewlineVisibility();
    }

    private void UpdateNewlineVisibility() =>
        _newlineCombo.IsEnabled = (_formatCombo.SelectedValue as FileSendFormat?) == FileSendFormat.TextLines;

    private void Browse()
    {
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Title = "选择要发送的文件",
            Filter = "所有文件 (*.*)|*.*|文本文件 (*.txt)|*.txt|二进制文件 (*.bin)|*.bin|HEX 文件 (*.hex)|*.hex",
        };
        if (dialog.ShowDialog(this) == true)
        {
            _pathEdit.Text = dialog.FileName;
        }
    }

    private void ToggleSend()
    {
        if (_thread is { IsAlive: true })
        {
            // 停止
            _cts?.Cancel();
            SetStatus("正在停止...");
            return;
        }

        var path = _pathEdit.Text.Trim();
        if (path.Length == 0)
        {
            MessageBox.Show(this, "请先选择文件。", "文件发送", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (!File.Exists(path))
        {
            MessageBox.Show(this, "文件不存在。", "文件发送", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (!int.TryParse(_chunkEdit.Text.Trim(), out var chunkSize) || chunkSize < 1)
        {
            chunkSize = 512;
        }

        if (!int.TryParse(_intervalEdit.Text.Trim(), out var interval) || interval < 0)
        {
            interval = 0;
        }

        var format = _formatCombo.SelectedValue as FileSendFormat? ?? FileSendFormat.HexText;
        var newline = _newlineCombo.SelectedValue as string ?? "";

        List<byte[]> blocks;
        try
        {
            if (format == FileSendFormat.RawBinary)
            {
                var bytes = File.ReadAllBytes(path);
                blocks = FileSend.Chunk(bytes, chunkSize);
            }
            else
            {
                var content = File.ReadAllText(path, Utf8);
                blocks = FileSend.Prepare(content, [], format, Utf8, newline, chunkSize);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            MessageBox.Show(this, $"读取文件失败：\n{ex.Message}", "文件发送",
                            MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (blocks.Count == 0)
        {
            MessageBox.Show(this, "文件内容为空或格式无法解析。", "文件发送",
                            MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _progress.Maximum = blocks.Count;
        _progress.Value = 0;
        _startButton.Content = "停止";
        _startButton.Tag = "danger";

        _cts = new CancellationTokenSource();
        var token = _cts.Token;
        _thread = new Thread(() => SendLoop(blocks, interval, token))
        {
            IsBackground = true,
            Name = "OhmyPort.FileSend",
        };
        _thread.Start();
    }

    private void SendLoop(List<byte[]> blocks, int interval, CancellationToken token)
    {
        for (var i = 0; i < blocks.Count; i++)
        {
            if (token.IsCancellationRequested)
            {
                ReportDone("已取消");
                return;
            }

            if (!_send(blocks[i]))
            {
                ReportDone("发送失败：串口未打开或写入出错");
                return;
            }

            ReportProgress(i + 1, blocks.Count);

            if (interval > 0 && i < blocks.Count - 1 && !token.IsCancellationRequested)
            {
                Thread.Sleep(interval);
            }
        }

        ReportDone("发送完成");
    }

    private void ReportProgress(int done, int total) =>
        Dispatcher.BeginInvoke(() =>
        {
            _progress.Value = done;
            _status.Text = $"已发送 {done}/{total} 块";
        });

    private void ReportDone(string message) =>
        Dispatcher.BeginInvoke(() =>
        {
            _status.Text = message;
            _progress.Value = _progress.Maximum;
            _startButton.Content = "开始发送";
            _startButton.Tag = "accent";
        });

    private void SetStatus(string message) =>
        Dispatcher.BeginInvoke(() => _status.Text = message);

    protected override void OnClosed(EventArgs e)
    {
        _cts?.Cancel();
        base.OnClosed(e);
    }
}
