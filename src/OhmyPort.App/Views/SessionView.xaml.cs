using System.Collections.Concurrent;
using System.ComponentModel;
using System.IO.Ports;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using OhmyPort.App.Controls;
using OhmyPort.Core;
using OhmyPort.Core.Serial;
using SerialFrame = OhmyPort.Core.Serial.Frame;

namespace OhmyPort.App.Views;

/// <summary>一条日志记录的方向。</summary>
public enum LogDirection
{
    Rx,
    Tx,
    Sys,
}

/// <summary>发送辅助等下拉项的通用包装：显示名 + 实际值。</summary>
public sealed record Option(string Label, object Value)
{
    public override string ToString() => Label;
}

/// <summary>
/// 单个串口会话：独立的串口参数、显示、记录、统计。
/// 对应 Python 版 serial_tool.SerialSession。
/// </summary>
public partial class SessionView : UserControl, INotifyPropertyChanged
{
    private readonly SerialMonitor _monitor = new();
    private readonly ConcurrentQueue<LogRecord> _pending = new();
    private readonly Queue<LogRecord> _buffer = new();
    private readonly DispatcherTimer _flushTimer;
    private readonly List<string> _pausedLines = [];

    private Encoding _encoding = SendCodec.GetEncoding("utf-8");
    private bool _paused;
    private bool _hexView;
    private long _txBytes;
    private string _connectedPort = "";

    public SessionView()
    {
        InitializeComponent();
        PopulateFixedItems();
        WireEvents();

        _flushTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(UiDefaults.FlushMs),
        };
        _flushTimer.Tick += (_, _) => Flush();
        _flushTimer.Start();

        _monitor.Received += OnReceived;
        Loaded += async (_, _) => await RefreshPortsAsync();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public event EventHandler? TitleChanged;

    public event EventHandler? StatusChanged;

    /// <summary>会话序号（用于默认标题「串口N」）。</summary>
    public int Index { get; set; }

    public string Title => _monitor.IsConnected ? $"● {_connectedPort}" : $"串口{Index + 1}";

    public bool IsConnected => _monitor.IsConnected;

    public string StatusText
    {
        get
        {
            var port = (PortCombo.SelectedItem as PortInfo?)?.PortName ?? "未选端口";
            var baud = string.IsNullOrWhiteSpace(BaudCombo.Text) ? "115200" : BaudCombo.Text;
            var enc = (EncodingCombo.SelectedItem as Option)?.Label ?? "UTF-8";
            var conn = _monitor.IsConnected ? "已连接" : "未连接";
            return $"{port} @ {baud} · {enc} · {conn}    " +
                   $"RX: {TextUtil.FormatBytes(Interlocked.Read(ref _monitor.RxBytes))}   " +
                   $"TX: {TextUtil.FormatBytes(_txBytes)}";
        }
    }

    /// <summary>串口参数面板是否可见（视图菜单控制）。</summary>
    public bool ParamsVisible
    {
        get => ParamsPanel.Visibility == Visibility.Visible;
        set => ParamsPanel.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
    }

    /// <summary>发送面板是否可见（视图菜单控制）。</summary>
    public bool SendVisible
    {
        get => SendPanel.Visibility == Visibility.Visible;
        set => SendPanel.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
    }

    /// <summary>HEX 显示开关（视图菜单控制）。</summary>
    public bool HexView
    {
        get => HexViewCheck.IsChecked == true;
        set => HexViewCheck.IsChecked = value;
    }

    /// <summary>固定显示开关（视图菜单控制）。</summary>
    public bool FixedView
    {
        get => FixedCheck.IsChecked == true;
        set => FixedCheck.IsChecked = value;
    }

    /// <summary>会话序号变化后刷新标题。</summary>
    public void RefreshTitle() => RaiseTitleChanged();

    // ---------- 初始化 ----------

    private void PopulateFixedItems()
    {
        foreach (var baud in SerialDefaults.Bauds)
        {
            BaudCombo.Items.Add(baud);
        }

        BaudCombo.Text = "115200";

        DataBitsCombo.DisplayMemberPath = nameof(Option.Label);
        DataBitsCombo.SelectedValuePath = nameof(Option.Value);
        DataBitsCombo.ItemsSource = new[]
        {
            new Option("8", 8), new Option("7", 7), new Option("6", 6), new Option("5", 5),
        };
        DataBitsCombo.SelectedIndex = 0;

        StopBitsCombo.DisplayMemberPath = nameof(Option.Label);
        StopBitsCombo.SelectedValuePath = nameof(Option.Value);
        StopBitsCombo.ItemsSource = new[]
        {
            new Option("1", StopBits.One), new Option("1.5", StopBits.OnePointFive), new Option("2", StopBits.Two),
        };
        StopBitsCombo.SelectedIndex = 0;

        ParityCombo.DisplayMemberPath = nameof(Option.Label);
        ParityCombo.SelectedValuePath = nameof(Option.Value);
        ParityCombo.ItemsSource = new[]
        {
            new Option("无", Parity.None), new Option("奇", Parity.Odd), new Option("偶", Parity.Even),
            new Option("标记", Parity.Mark), new Option("空格", Parity.Space),
        };
        ParityCombo.SelectedIndex = 0;

        FlowCombo.DisplayMemberPath = nameof(Option.Label);
        FlowCombo.SelectedValuePath = nameof(Option.Value);
        FlowCombo.ItemsSource = new[]
        {
            new Option("无", Handshake.None), new Option("RTS/CTS", Handshake.RequestToSend),
            new Option("DTR/DSR", Handshake.None), new Option("XON/XOFF", Handshake.XOnXOff),
        };
        FlowCombo.SelectedIndex = 0;

        EncodingCombo.DisplayMemberPath = nameof(Option.Label);
        EncodingCombo.SelectedValuePath = nameof(Option.Value);
        EncodingCombo.ItemsSource = SerialDefaults.Encodings
            .Select(e => new Option(e.Label, e.Key))
            .ToArray();
        EncodingCombo.SelectedIndex = 0;

        NewlineCombo.DisplayMemberPath = nameof(Option.Label);
        NewlineCombo.SelectedValuePath = nameof(Option.Value);
        NewlineCombo.ItemsSource = SerialDefaults.Newlines
            .Select(n => new Option(n.Label, n.Value))
            .ToArray();
        NewlineCombo.SelectedIndex = 0;

        PortCombo.DisplayMemberPath = nameof(PortInfo.Display);
        PortCombo.SelectedValuePath = nameof(PortInfo.PortName);
    }

    private void WireEvents()
    {
        RefreshButton.Click += async (_, _) => await RefreshPortsAsync();
        ConnectButton.Click += OnConnectClick;
        PauseButton.Click += OnPauseClick;
        ClearButton.Click += (_, _) => ClearLog();
        SendButton.Click += (_, _) => SendRaw();

        SendCombo.PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter)
            {
                SendRaw();
                e.Handled = true;
            }
        };

        EncodingCombo.SelectionChanged += (_, _) =>
        {
            if (EncodingCombo.SelectedValue is string key)
            {
                _encoding = SendCodec.GetEncoding(key);
                ReRender();
            }
        };

        HexViewCheck.Checked += (_, _) => SetHexView(true);
        HexViewCheck.Unchecked += (_, _) => SetHexView(false);

        DtrCheck.Checked += (_, _) => _monitor.SetDtr(true);
        DtrCheck.Unchecked += (_, _) => _monitor.SetDtr(false);
        RtsCheck.Checked += (_, _) => _monitor.SetRts(true);
        RtsCheck.Unchecked += (_, _) => _monitor.SetRts(false);

        CopyMenuItem.Click += (_, _) => CopySelection();
        CopyAllMenuItem.Click += (_, _) => CopyAll();
        ClearMenuItem.Click += (_, _) => ClearLog();
    }

    // ---------- 端口 ----------

    public async Task RefreshPortsAsync()
    {
        var previous = (PortCombo.SelectedItem as PortInfo?)?.PortName;
        var ports = await PortEnumerator.ListPortsAsync();

        PortCombo.ItemsSource = ports;
        PortCombo.SelectedValue = ports.Any(p => string.Equals(p.PortName, previous, StringComparison.OrdinalIgnoreCase))
            ? previous
            : ports.Count > 0 ? ports[0].PortName : null;
    }

    // ---------- 连接 ----------

    private void OnConnectClick(object sender, RoutedEventArgs e)
    {
        if (_monitor.IsConnected)
        {
            Disconnect();
            return;
        }

        if (PortCombo.SelectedItem is not PortInfo port)
        {
            MessageBox.Show(Window.GetWindow(this)!, "没有可用的串口，请先插入设备并点击「刷新」。",
                            "串口连接", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (!int.TryParse(BaudCombo.Text.Trim(), out var baud) || baud <= 0)
        {
            MessageBox.Show(Window.GetWindow(this)!, "波特率无效，请输入正整数（例如 115200）。",
                            "串口连接", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        var settings = new SerialSettings(
            port.PortName,
            baud,
            DataBitsCombo.SelectedValue as int? ?? 8,
            ParityCombo.SelectedValue as Parity? ?? Parity.None,
            StopBitsCombo.SelectedValue as StopBits? ?? StopBits.One,
            FlowCombo.SelectedValue as Handshake? ?? Handshake.None);

        if (!_monitor.Connect(settings))
        {
            MessageBox.Show(
                Window.GetWindow(this)!,
                $"串口 {port.PortName} 打开失败：\n{_monitor.LastError}\n\n" +
                "常见原因：端口不存在 / 被其它软件占用 / 无访问权限。",
                "串口连接", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _connectedPort = port.PortName;
        _monitor.SetDtr(DtrCheck.IsChecked == true);
        _monitor.SetRts(RtsCheck.IsChecked == true);
        AddSystem($"已打开 {port.PortName}，波特率 {baud}");
        UpdateConnectionUi();
    }

    private void Disconnect()
    {
        _monitor.Disconnect();
        AddSystem("串口已关闭");
        UpdateConnectionUi();
    }

    private void UpdateConnectionUi()
    {
        var connected = _monitor.IsConnected;
        ConnectButton.Content = connected ? "关闭串口" : "打开串口";
        ConnectButton.Tag = connected ? null : "accent";
        PortCombo.IsEnabled = !connected;
        BaudCombo.IsEnabled = !connected;
        RefreshButton.IsEnabled = !connected;

        RaiseTitleChanged();
        RaiseStatusChanged();
    }

    // ---------- 接收 / 显示 ----------

    private void OnReceived(IReadOnlyList<SerialFrame> frames)
    {
        var now = DateTime.Now;
        foreach (var frame in frames)
        {
            _pending.Enqueue(new LogRecord(now, LogDirection.Rx, frame.Data, null, frame.ChecksumOk));
        }
    }

    private void Flush()
    {
        if (_pending.IsEmpty)
        {
            return;
        }

        var lines = new List<string>();
        while (_pending.TryDequeue(out var record))
        {
            AppendToBuffer(record);
            lines.Add(FormatLine(record));

            if (!record.ChecksumOk && record.Data is not null)
            {
                lines.Add(FormatLine(new LogRecord(record.Time, LogDirection.Sys,
                                                   null, $"帧校验失败: {ToHex(record.Data)}")));
            }
        }

        if (_paused)
        {
            _pausedLines.AddRange(lines);
            if (_pausedLines.Count > UiDefaults.MaxLines)
            {
                _pausedLines.RemoveRange(0, _pausedLines.Count - UiDefaults.MaxLines);
            }

            return;
        }

        LogText.AppendLines(lines, FollowTail);
        RaiseStatusChanged();
    }

    private void AppendToBuffer(LogRecord record)
    {
        _buffer.Enqueue(record);
        while (_buffer.Count > UiDefaults.MaxLines)
        {
            _buffer.Dequeue();
        }
    }

    private bool FollowTail => FixedCheck.IsChecked != true;

    private string FormatLine(LogRecord record)
    {
        var ts = record.Time.ToString("HH:mm:ss.fff");
        return record.Direction switch
        {
            LogDirection.Tx => $"[{ts}] {LogView.TxMark}{DisplayBody(record.Data)}",
            LogDirection.Sys => $"[{ts}] {LogView.SysMark}{record.Text}",
            _ => $"[{ts}] {DisplayBody(record.Data)}",
        };
    }

    private string DisplayBody(byte[]? data)
    {
        if (data is null)
        {
            return "";
        }

        return _hexView ? ToHex(data) : _encoding.GetString(data);
    }

    private static string ToHex(byte[] data)
    {
        var sb = new StringBuilder(data.Length * 3);
        foreach (var b in data)
        {
            if (sb.Length > 0)
            {
                sb.Append(' ');
            }

            sb.Append(b.ToString("X2"));
        }

        return sb.ToString();
    }

    private void SetHexView(bool enabled)
    {
        if (_hexView == enabled)
        {
            return;
        }

        _hexView = enabled;
        ReRender();
    }

    /// <summary>按当前编码 / HEX 设置重建整个显示区（对应 Python 版 _rerender）。</summary>
    private void ReRender()
    {
        LogText.ClearAll();
        LogText.AppendLines(_buffer.Select(FormatLine).ToList(), FollowTail);
    }

    // ---------- 日志操作 ----------

    private void OnPauseClick(object sender, RoutedEventArgs e)
    {
        _paused = !_paused;
        PauseButton.Content = _paused ? "继续" : "暂停";

        if (!_paused && _pausedLines.Count > 0)
        {
            LogText.AppendLines(_pausedLines, FollowTail);
            _pausedLines.Clear();
        }
    }

    private void ClearLog()
    {
        while (_pending.TryDequeue(out _))
        {
            // 丢弃待显示队列
        }

        _buffer.Clear();
        _pausedLines.Clear();
        LogText.ClearAll();
        RaiseStatusChanged();
    }

    private void CopySelection()
    {
        if (LogText.SelectionLength <= 0)
        {
            AddSystem("未选中文本");
            return;
        }

        LogText.Copy();
    }

    private void CopyAll()
    {
        if (LogText.AllText.Length == 0)
        {
            return;
        }

        try
        {
            Clipboard.SetText(LogText.AllText);
        }
        catch (System.Runtime.InteropServices.COMException)
        {
            AddSystem("复制失败：剪贴板被其它程序占用");
        }
    }

    // ---------- 发送 ----------

    private void SendRaw()
    {
        var text = SendCombo.Text;
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        byte[] data;
        if (HexSendCheck.IsChecked == true)
        {
            var parsed = SendCodec.ParseHex(text);
            if (parsed is null)
            {
                AddSystem("HEX 格式无效（示例：01 03 00 0A）");
                return;
            }

            data = parsed;
        }
        else
        {
            var newline = NewlineCombo.SelectedValue as string ?? "";
            data = [.. SendCodec.ParseEscaped(text, _encoding), .. _encoding.GetBytes(newline)];
        }

        if (!_monitor.IsConnected)
        {
            AddSystem("串口未打开，无法发送");
            return;
        }

        if (_monitor.Send(data))
        {
            _txBytes += data.Length;
            _pending.Enqueue(new LogRecord(DateTime.Now, LogDirection.Tx, data, null));
            AddSendHistory(text);
            RaiseStatusChanged();
        }
    }

    private void AddSendHistory(string text)
    {
        if (!SendCombo.Items.Contains(text))
        {
            SendCombo.Items.Add(text);
        }

        while (SendCombo.Items.Count > UiDefaults.SendHistoryMax)
        {
            SendCombo.Items.RemoveAt(0);
        }
    }

    private void AddSystem(string text) =>
        _pending.Enqueue(new LogRecord(DateTime.Now, LogDirection.Sys, null, text));

    // ---------- 通知 ----------

    private void RaiseTitleChanged()
    {
        TitleChanged?.Invoke(this, EventArgs.Empty);
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Title)));
    }

    private void RaiseStatusChanged() => StatusChanged?.Invoke(this, EventArgs.Empty);

    public void Shutdown()
    {
        _flushTimer.Stop();
        _monitor.Disconnect();
    }

    /// <summary>供后续里程碑（日志录制 / 过滤）复用：当前显示区控件。</summary>
    public LogView LogControl => LogText;
}

/// <summary>一条待显示 / 已缓存的日志。</summary>
public sealed record LogRecord(
    DateTime Time,
    LogDirection Direction,
    byte[]? Data,
    string? Text,
    bool ChecksumOk = true);
