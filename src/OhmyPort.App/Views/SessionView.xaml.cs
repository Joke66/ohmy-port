using System.Collections.Concurrent;
using System.ComponentModel;
using System.IO;
using System.IO.Ports;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using Microsoft.Win32;
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
    private readonly DispatcherTimer _hotplugTimer;

    private HashSet<string> _knownPorts = new(StringComparer.OrdinalIgnoreCase);
    private LogFilter _filter = new();
    private bool _filterEnabled;
    private Encoding _encoding = SendCodec.GetEncoding("utf-8");
    private bool _paused;
    private bool _hexView;
    private long _txBytes;
    private string _connectedPort = "";
    private string? _rememberedPort;

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

        _hotplugTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(UiDefaults.HotplugMs),
        };
        _hotplugTimer.Tick += (_, _) => CheckHotplug();
        _hotplugTimer.Start();
        _knownPorts = new HashSet<string>(SerialPort.GetPortNames(), StringComparer.OrdinalIgnoreCase);

        _monitor.Received += OnReceived;
        Loaded += async (_, _) => await RefreshPortsAsync();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public event EventHandler? TitleChanged;

    public event EventHandler? StatusChanged;

    /// <summary>会话序号（用于默认标题「串口N」）。</summary>
    public int Index { get; set; }

    public string Title => _monitor.IsConnected ? _connectedPort : $"串口{Index + 1}";

    public bool IsConnected => _monitor.IsConnected;

    /// <summary>启动时恢复的端口名（在端口列表异步加载完成后选中）。</summary>
    public string? RememberedPort
    {
        get => _rememberedPort;
        set => _rememberedPort = value;
    }

    /// <summary>当前选中的端口名（配置持久化用）。</summary>
    public string? SelectedPort => (PortCombo.SelectedItem as PortInfo?)?.PortName;

    /// <summary>波特率输入框文本（配置持久化用）。</summary>
    public string BaudText
    {
        get => BaudCombo.Text;
        set => BaudCombo.Text = value;
    }

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

    /// <summary>关键词过滤面板是否可见（视图菜单控制）。</summary>
    public bool FilterVisible
    {
        get => FilterPanel.Visibility == Visibility.Visible;
        set => FilterPanel.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
    }

    /// <summary>自动换行开关（主窗口全局设置，应用到主日志区与命中分栏）。</summary>
    public bool WrapEnabled
    {
        get => LogText.WordWrap;
        set
        {
            LogText.WordWrap = value;
            MatchedText.WordWrap = value;
        }
    }

    /// <summary>当前日志字号（配置持久化用）。</summary>
    public double FontSizeValue => LogText.FontSize;

    public void SetFontSize(double size)
    {
        LogText.FontSize = size;
        MatchedText.FontSize = size;
    }

    public void ZoomIn(int step = 1)
    {
        LogText.ZoomIn(step);
        MatchedText.ZoomIn(step);
    }

    public void ZoomOut(int step = 1)
    {
        LogText.ZoomOut(step);
        MatchedText.ZoomOut(step);
    }

    public void ResetZoom()
    {
        LogText.ResetZoom();
        MatchedText.ResetZoom();
    }

    /// <summary>会话序号变化后刷新标题。</summary>
    public void RefreshTitle() => RaiseTitleChanged();

    // ---------- 过滤持久化（配置保存 / 恢复用） ----------

    public string FilterKeywordsText => KeywordEdit.Text;

    public string FilterModeKey => ModeCombo.SelectedValue as string ?? FilterModes.Highlight;

    public bool FilterCaseSensitive => CaseCheck.IsChecked == true;

    public bool FilterEnabledState => _filterEnabled;

    /// <summary>从配置恢复过滤状态。</summary>
    public void ApplyRememberedFilter(string keywords, string mode, bool caseSensitive, bool enabled)
    {
        KeywordEdit.Text = keywords;
        if (ModeCombo.Items.Cast<Option>().Any(o => (string)o.Value == mode))
        {
            ModeCombo.SelectedValue = mode;
        }

        CaseCheck.IsChecked = caseSensitive;

        if (enabled)
        {
            _filterEnabled = true;
            FilterButton.Content = "关闭";
            ApplyFilter();
        }
    }

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

        ModeCombo.DisplayMemberPath = nameof(Option.Label);
        ModeCombo.SelectedValuePath = nameof(Option.Value);
        ModeCombo.ItemsSource = new[]
        {
            new Option("显示全部并高亮", FilterModes.Highlight),
            new Option("仅显示命中行", FilterModes.Include),
            new Option("排除命中行", FilterModes.Exclude),
            new Option("上下分栏显示命中行", FilterModes.Split),
        };
        ModeCombo.SelectedIndex = 0;

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

        FilterButton.Click += (_, _) => ToggleFilter();
        ModeCombo.SelectionChanged += (_, _) =>
        {
            if (_filterEnabled)
            {
                ApplyFilter();
            }
        };
        CaseCheck.Click += (_, _) =>
        {
            if (_filterEnabled)
            {
                ApplyFilter();
            }
        };
        ClearMatchedButton.Click += (_, _) => ClearMatched();

        DtrCheck.Checked += (_, _) => _monitor.SetDtr(true);
        DtrCheck.Unchecked += (_, _) => _monitor.SetDtr(false);
        RtsCheck.Checked += (_, _) => _monitor.SetRts(true);
        RtsCheck.Unchecked += (_, _) => _monitor.SetRts(false);

        CopyMenuItem.Click += (_, _) => CopySelection();
        CopyAllMenuItem.Click += (_, _) => CopyAll();
        SaveLogMenuItem.Click += (_, _) => SaveLog();
        ClearMenuItem.Click += (_, _) => ClearLog();
    }

    private void OnKeywordKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            if (!_filterEnabled)
            {
                _filterEnabled = true;
                FilterButton.Content = "关闭";
            }

            ApplyFilter();
            e.Handled = true;
        }
    }

    // ---------- 端口 ----------

    public async Task RefreshPortsAsync()
    {
        var preferred = (PortCombo.SelectedItem as PortInfo?)?.PortName ?? _rememberedPort;
        var ports = await PortEnumerator.ListPortsAsync();

        PortCombo.ItemsSource = ports;
        PortCombo.SelectedValue = ports.Any(p => string.Equals(p.PortName, preferred, StringComparison.OrdinalIgnoreCase))
            ? preferred
            : ports.Count > 0 ? ports[0].PortName : null;

        _knownPorts = new HashSet<string>(ports.Select(p => p.PortName), StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>热插拔检测：连接中端口被拔出则自动断开；断开状态下端口集合变化则刷新列表。</summary>
    private async void CheckHotplug()
    {
        var current = new HashSet<string>(SerialPort.GetPortNames(), StringComparer.OrdinalIgnoreCase);

        if (_monitor.IsConnected)
        {
            var port = (PortCombo.SelectedItem as PortInfo?)?.PortName;
            if (!string.IsNullOrEmpty(port) && !current.Contains(port))
            {
                _knownPorts = current;
                DisconnectWithMessage(null);
                AddSystem($"串口 {port} 已断开");
            }

            return;
        }

        if (!current.SetEquals(_knownPorts))
        {
            _knownPorts = current;
            await RefreshPortsAsync();
        }
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

    private void Disconnect() => DisconnectWithMessage("串口已关闭");

    private void DisconnectWithMessage(string? message)
    {
        _monitor.Disconnect();
        if (message is not null)
        {
            AddSystem(message);
        }

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

        OnPropertyChanged(nameof(IsConnected));
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
        var matchedLines = new List<string>();

        while (_pending.TryDequeue(out var record))
        {
            AppendToBuffer(record);

            // 帧校验失败：追加系统提示（sys 不受暂停影响，不参与过滤）
            if (!record.ChecksumOk && record.Data is not null)
            {
                lines.Add(FormatLine(new LogRecord(record.Time, LogDirection.Sys,
                                                   null, $"帧校验失败: {ToHex(record.Data)}")));
            }

            var text = PayloadText(record);
            var visible = _filter.Visible(text);
            var isMatch = _filter.Mode == FilterModes.Split && _filter.Matched(text).Count > 0;

            // 暂停只冻结 rx/tx 显示，sys 仍实时显示；buffer 继续积累，恢复时全量重建
            if (_paused && record.Direction != LogDirection.Sys)
            {
                continue;
            }

            if (visible)
            {
                lines.Add(FormatLine(record));
            }

            if (isMatch)
            {
                matchedLines.Add(FormatLine(record));
            }
        }

        if (lines.Count > 0)
        {
            LogText.AppendLines(lines, FollowTail);
        }

        if (matchedLines.Count > 0)
        {
            MatchedText.AppendLines(matchedLines, follow: true);
        }

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

    /// <summary>记录用于过滤判断的文本（按当前编码解码，不受 HEX 显示影响）。</summary>
    private string PayloadText(LogRecord record)
    {
        if (record.Direction == LogDirection.Sys)
        {
            return record.Text ?? "";
        }

        if (record.Data is null)
        {
            return "";
        }

        return _encoding.GetString(record.Data);
    }

    /// <summary>按当前编码 / HEX / 过滤设置重建整个显示区（对应 Python 版 _rerender）。</summary>
    private void ReRender()
    {
        LogText.ClearAll();

        var visibleLines = _buffer
            .Where(r => _filter.Visible(PayloadText(r)))
            .Select(FormatLine)
            .ToList();
        LogText.AppendLines(visibleLines, FollowTail);

        ReRenderMatched();
    }

    /// <summary>重建命中结果分栏（split 模式）。</summary>
    private void ReRenderMatched()
    {
        MatchedText.ClearAll();
        if (_filter.Mode != FilterModes.Split)
        {
            return;
        }

        var matchedLines = _buffer
            .Where(r => _filter.Matched(PayloadText(r)).Count > 0)
            .Select(FormatLine)
            .ToList();
        if (matchedLines.Count > 0)
        {
            MatchedText.AppendLines(matchedLines, follow: true);
        }
    }

    // ---------- 日志操作 ----------

    private void OnPauseClick(object sender, RoutedEventArgs e)
    {
        _paused = !_paused;
        PauseButton.Content = _paused ? "继续" : "暂停";

        if (!_paused)
        {
            ReRender();
        }
    }

    private void ClearLog()
    {
        while (_pending.TryDequeue(out _))
        {
            // 丢弃待显示队列
        }

        _buffer.Clear();
        LogText.ClearAll();
        MatchedText.ClearAll();
        RaiseStatusChanged();
    }

    // ---------- 过滤 ----------

    private void ToggleFilter()
    {
        if (_filterEnabled)
        {
            _filterEnabled = false;
            _filter = new LogFilter();
            FilterButton.Content = "应用";
            LogText.SetKeywords([], caseSensitive: false);
            MatchedText.SetKeywords([], caseSensitive: false);
            ReRender();
            MatchedPanel.Visibility = Visibility.Collapsed;
        }
        else
        {
            _filterEnabled = true;
            FilterButton.Content = "关闭";
            ApplyFilter();
        }
    }

    private void ApplyFilter()
    {
        if (!_filterEnabled)
        {
            return;
        }

        _filter = new LogFilter(
            LogFilter.ParseKeywords(KeywordEdit.Text),
            ModeCombo.SelectedValue as string ?? FilterModes.Highlight,
            CaseCheck.IsChecked == true);

        LogText.SetKeywords(_filter.Keywords, _filter.CaseSensitive);
        MatchedText.SetKeywords(_filter.Keywords, _filter.CaseSensitive);
        ReRender();

        MatchedPanel.Visibility = _filter.Mode == FilterModes.Split
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    private void ClearMatched() => MatchedText.ClearAll();

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

    public void SaveLog()
    {
        if (_buffer.Count == 0)
        {
            AddSystem("当前没有可保存的日志");
            return;
        }

        var dialog = new SaveFileDialog
        {
            Title = "保存串口日志",
            Filter = "文本文件 (*.txt)|*.txt",
            FileName = $"{LogBasename}.txt",
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true)
        {
            return;
        }

        try
        {
            File.WriteAllLines(dialog.FileName, _buffer.Select(FormatRecordLine), new UTF8Encoding(false));
            AddSystem($"日志已保存: {dialog.FileName}");
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            MessageBox.Show(Window.GetWindow(this)!, ex.Message, "保存失败",
                            MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    /// <summary>日志文件基线名（优先端口名，未连接用 serial）。</summary>
    private string LogBasename =>
        (PortCombo.SelectedItem as PortInfo?)?.PortName is { Length: > 0 } port ? port : "serial";

    /// <summary>落盘格式：固定为文本形式，不受「HEX 显示」切换影响（对应 Python 版 _record_line）。</summary>
    private string FormatRecordLine(LogRecord record)
    {
        var ts = record.Time.ToString("HH:mm:ss.fff");
        return record.Direction switch
        {
            LogDirection.Tx => $"[{ts}] {LogView.TxMark}{PayloadText(record)}",
            LogDirection.Sys => $"[{ts}] {LogView.SysMark}{record.Text}",
            _ => $"[{ts}] {PayloadText(record)}",
        };
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

    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

    private void RaiseTitleChanged()
    {
        TitleChanged?.Invoke(this, EventArgs.Empty);
        OnPropertyChanged(nameof(Title));
    }

    private void RaiseStatusChanged() => StatusChanged?.Invoke(this, EventArgs.Empty);

    public void Shutdown()
    {
        _flushTimer.Stop();
        _hotplugTimer.Stop();
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
