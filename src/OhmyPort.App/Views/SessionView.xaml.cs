using System.Collections.Concurrent;
using System.ComponentModel;
using System.IO;
using System.IO.Ports;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Microsoft.Win32;
using OhmyPort.App.Controls;
using OhmyPort.Core;
using OhmyPort.Core.Models;
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
    private readonly OhmyPort.Core.Logging.LogManager _logmgr = new();

    private HashSet<string> _knownPorts = new(StringComparer.OrdinalIgnoreCase);
    private LogFilter _filter = new();
    private bool _filterEnabled;
    private Encoding _encoding = SendCodec.GetEncoding("utf-8");
    private bool _paused;
    private bool _hexView;
    private long _txBytes;
    private string _connectedPort = "";
    private string? _rememberedPort;
    private string? _customTitle;
    private bool _responsePending;
    private int _histIdx = -1;
    private string _timestamp = TimestampModes.Full;

    /// <summary>实时速率采样（1s）。</summary>
    private readonly DispatcherTimer _rateTimer;
    private long _lastRxBytes;
    private long _lastTxBytes;
    private long _rxRate;
    private long _txRate;

    /// <summary>协议字段定义（按帧解析后用于结构化显示）。</summary>
    private List<ProtocolField> _protocolFields = [];

    /// <summary>数据区在帧内的起始下标（帧头 + 长度字段长度），字段偏移以此为准。</summary>
    private int _frameDataOffset;

    /// <summary>最近一帧（Rx），用于字段解析显示。</summary>
    private byte[]? _latestFrame;
    private bool _fieldsDirty;
    private long _lastFieldsRefreshTicks;

    /// <summary>曲线数据（实时曲线窗口从这里取数）。</summary>
    private readonly PlotHub _plotHub = new();

    /// <summary>曲线提取规则（配置持久化 + 窗口编辑回写用）。</summary>
    private List<PlotRuleConfig> _plotRules = [];

    /// <summary>日志保存目录（由主窗口注入并同步）。</summary>
    public string LogDirectory { get; set; } = AppPaths.DefaultLogDir;

    /// <summary>日志分片大小（MB）。</summary>
    public int ShardMb { get; set; } = 5;

    /// <summary>连接后是否自动开始记录（由主窗口注入并同步）。</summary>
    public bool AutoRecord { get; set; } = true;

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

        _rateTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromSeconds(1),
        };
        _rateTimer.Tick += (_, _) => SampleRate();
        _rateTimer.Start();

        _knownPorts = new HashSet<string>(SerialPort.GetPortNames(), StringComparer.OrdinalIgnoreCase);

        _monitor.Received += OnReceived;
        Loaded += async (_, _) => await RefreshPortsAsync();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public event EventHandler? TitleChanged;

    public event EventHandler? StatusChanged;

    /// <summary>会话序号（用于默认标题「串口N」）。</summary>
    public int Index { get; set; }

    public string Title => _customTitle ?? (_monitor.IsConnected ? _connectedPort : $"串口{Index + 1}");

    /// <summary>自定义标题（重命名会话用；置 null 回退默认标题）。</summary>
    public string? CustomTitle
    {
        get => _customTitle;
        set
        {
            _customTitle = string.IsNullOrWhiteSpace(value) ? null : value;
            RaiseTitleChanged();
        }
    }

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
                   $"RX: {TextUtil.FormatBytes(Interlocked.Read(ref _monitor.RxBytes))}" +
                   $"{FormatRate(_rxRate)}   " +
                   $"TX: {TextUtil.FormatBytes(_txBytes)}" +
                   $"{FormatRate(_txRate)}";
        }
    }

    /// <summary>速率后缀（如 " · 1.2 KB/s"，速率为 0 时为空）。</summary>
    private static string FormatRate(long bytesPerSecond) =>
        bytesPerSecond > 0 ? $" · {TextUtil.FormatBytes(bytesPerSecond)}/s" : "";

    /// <summary>每秒采样一次 RX/TX 增量，得到实时速率。</summary>
    private void SampleRate()
    {
        var rx = Interlocked.Read(ref _monitor.RxBytes);
        _rxRate = rx - _lastRxBytes;
        _lastRxBytes = rx;
        _txRate = _txBytes - _lastTxBytes;
        _lastTxBytes = _txBytes;
        RaiseStatusChanged();
    }

    /// <summary>串口参数面板是否可见（视图菜单控制）。</summary>
    public bool ParamsVisible
    {
        get => ParamsPanel.Visibility == Visibility.Visible;
        set => SetPanelVisible(ParamsPanel, value);
    }

    /// <summary>发送面板是否可见（视图菜单控制）。</summary>
    public bool SendVisible
    {
        get => SendPanel.Visibility == Visibility.Visible;
        set => SetPanelVisible(SendPanel, value);
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
        set => SetPanelVisible(FilterPanel, value);
    }

    /// <summary>协议帧解析面板是否可见（视图菜单控制）。</summary>
    public bool ProtocolVisible
    {
        get => ProtocolPanel.Visibility == Visibility.Visible;
        set => SetPanelVisible(ProtocolPanel, value);
    }

    /// <summary>帧字段解析结果面板是否可见（视图菜单控制）。</summary>
    public bool FieldsVisible
    {
        get => FieldsPanel.Visibility == Visibility.Visible;
        set
        {
            SetPanelVisible(FieldsPanel, value);
            if (value)
            {
                RefreshFields();
            }
        }
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

    public bool FilterRegexState => RegexCheck.IsChecked == true;

    /// <summary>日志时间戳显示档位（配置持久化 / 恢复用）。</summary>
    public string TimestampMode
    {
        get => _timestamp;
        set
        {
            _timestamp = TimestampModes.All.Contains(value) ? value : TimestampModes.Full;
            ReRender();
        }
    }

    /// <summary>发送校验类型键（配置持久化用）。</summary>
    public string SendChecksumKey => ChecksumCombo.SelectedValue as string ?? ChecksumKeys.None;

    public bool FrameEnabledState => FrameEnableCheck.IsChecked == true;
    public string FrameHeaderText => FrameHeaderEdit.Text;
    public string FrameTailText => FrameTailEdit.Text;
    public int FrameLengthSizeValue => (FrameLengthCombo.SelectedValue as int?) ?? 0;
    public int FrameLengthBaseValue => int.TryParse(FrameLengthBaseEdit.Text.Trim(), out var v) ? v : 0;
    public bool FrameBigEndianValue => (FrameEndianCombo.SelectedValue as bool?) ?? true;
    public string FrameChecksumKey => FrameChecksumCombo.SelectedValue as string ?? ChecksumKeys.None;

    /// <summary>协议字段快照（配置持久化用）。</summary>
    public List<ProtocolField> ProtocolFieldsSnapshot => _protocolFields
        .Select(f => new ProtocolField
        {
            Name = f.Name,
            Offset = f.Offset,
            Type = f.Type,
            BigEndian = f.BigEndian,
            Length = f.Length,
            Scale = f.Scale,
            Bias = f.Bias,
        })
        .ToList();

    /// <summary>本会话的曲线数据（实时曲线窗口用）。</summary>
    public PlotHub Plot => _plotHub;

    /// <summary>当前曲线提取规则（配置持久化用）。</summary>
    public List<PlotRuleConfig> PlotRulesSnapshot =>
        _plotRules.Select(r => new PlotRuleConfig(r.Name, r.Pattern)).ToList();

    /// <summary>设置曲线提取规则（配置恢复 / 窗口编辑回写）。容量沿用当前值。</summary>
    public void SetPlotRules(IEnumerable<PlotRuleConfig>? rules)
    {
        _plotRules = (rules ?? [])
            .Where(r => r is not null && r.Name.Length > 0 && r.Pattern.Length > 0)
            .Select(r => new PlotRuleConfig(r.Name, r.Pattern))
            .ToList();

        _plotHub.Configure(_plotRules, _plotHub.Capacity);
    }

    /// <summary>从源会话复制全部配置状态（「复制会话」用，不复制运行状态）。</summary>
    public void CopyStateFrom(SessionView src)
    {
        BaudText = src.BaudText;
        RememberedPort = src.SelectedPort;
        CustomTitle = $"{src.Title} 副本";
        SetFontSize(src.FontSizeValue);

        ApplyRememberedFilter(
            src.FilterKeywordsText, src.FilterModeKey, src.FilterCaseSensitive,
            src.FilterEnabledState, src.FilterRegexState);

        ApplyRememberedProtocol(
            src.SendChecksumKey, src.FrameEnabledState, src.FrameHeaderText, src.FrameTailText,
            src.FrameLengthSizeValue, src.FrameLengthBaseValue, src.FrameBigEndianValue,
            src.FrameChecksumKey, src.ProtocolFieldsSnapshot);

        SetPlotRules(src.PlotRulesSnapshot);
        HexView = src.HexView;
        FixedView = src.FixedView;
        _timestamp = src.TimestampMode;
    }

    /// <summary>从配置恢复协议帧解析与发送校验状态。</summary>
    public void ApplyRememberedProtocol(string sendChecksum, bool frameEnabled, string frameHeader,
        string frameTail, int frameLengthSize, int frameLengthBase, bool frameBigEndian,
        string frameChecksum, IEnumerable<ProtocolField>? fields = null)
    {
        if (ChecksumCombo.Items.Cast<Option>().Any(o => (string)o.Value == sendChecksum))
        {
            ChecksumCombo.SelectedValue = sendChecksum;
        }

        _protocolFields = fields?.Where(f => f is not null).Select(f => new ProtocolField
        {
            Name = f.Name,
            Offset = f.Offset,
            Type = f.Type,
            BigEndian = f.BigEndian,
            Length = f.Length,
            Scale = f.Scale,
            Bias = f.Bias,
        }).ToList() ?? [];

        if (_protocolFields.Count > 0)
        {
            FieldsPanel.Visibility = Visibility.Visible;
        }

        FrameEnableCheck.IsChecked = frameEnabled;
        FrameHeaderEdit.Text = frameHeader;
        FrameTailEdit.Text = frameTail;

        if (FrameLengthCombo.Items.Cast<Option>().Any(o => (int)o.Value == frameLengthSize))
        {
            FrameLengthCombo.SelectedValue = frameLengthSize;
        }

        FrameLengthBaseEdit.Text = frameLengthBase.ToString();

        if (FrameEndianCombo.Items.Cast<Option>().Any(o => (bool)o.Value == frameBigEndian))
        {
            FrameEndianCombo.SelectedValue = frameBigEndian;
        }

        if (FrameChecksumCombo.Items.Cast<Option>().Any(o => (string)o.Value == frameChecksum))
        {
            FrameChecksumCombo.SelectedValue = frameChecksum;
        }

        ApplyProtocol();
    }

    /// <summary>从配置恢复过滤状态。</summary>
    public void ApplyRememberedFilter(string keywords, string mode, bool caseSensitive, bool enabled,
                                      bool regex = false)
    {
        KeywordEdit.Text = keywords;
        if (ModeCombo.Items.Cast<Option>().Any(o => (string)o.Value == mode))
        {
            ModeCombo.SelectedValue = mode;
        }

        CaseCheck.IsChecked = caseSensitive;
        RegexCheck.IsChecked = regex;

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

        // 发送校验 + 协议帧解析共用校验选项
        var checksumOptions = new[]
        {
            new Option("无", ChecksumKeys.None),
            new Option("SUM8", ChecksumKeys.Sum8),
            new Option("XOR8", ChecksumKeys.Xor8),
            new Option("CRC16-Modbus", ChecksumKeys.Crc16Modbus),
        };
        foreach (var combo in new[] { ChecksumCombo, FrameChecksumCombo })
        {
            combo.DisplayMemberPath = nameof(Option.Label);
            combo.SelectedValuePath = nameof(Option.Value);
            combo.ItemsSource = checksumOptions;
            combo.SelectedIndex = 0;
        }

        FrameLengthCombo.DisplayMemberPath = nameof(Option.Label);
        FrameLengthCombo.SelectedValuePath = nameof(Option.Value);
        FrameLengthCombo.ItemsSource = new[]
        {
            new Option("无", 0), new Option("1", 1), new Option("2", 2), new Option("4", 4),
        };
        FrameLengthCombo.SelectedIndex = 0;

        FrameEndianCombo.DisplayMemberPath = nameof(Option.Label);
        FrameEndianCombo.SelectedValuePath = nameof(Option.Value);
        FrameEndianCombo.ItemsSource = new[]
        {
            new Option("大端", true), new Option("小端", false),
        };
        FrameEndianCombo.SelectedIndex = 0;

        FrameLengthBaseEdit.Text = "0";

        PortCombo.DisplayMemberPath = nameof(PortInfo.Display);
        PortCombo.SelectedValuePath = nameof(PortInfo.PortName);
    }

    private void WireEvents()
    {
        RefreshButton.Click += async (_, _) => await RefreshPortsAsync();
        ConnectButton.Click += OnConnectClick;
        PauseButton.Click += OnPauseClick;
        ClearButton.Click += (_, _) => ClearLog();
        RecordButton.Click += (_, _) => ToggleRecord();
        SendButton.Click += (_, _) => SendRaw();

        SendCombo.PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter)
            {
                SendRaw();
                e.Handled = true;
            }
            else if (!SendCombo.IsDropDownOpen && e.Key == Key.Up)
            {
                RecallHistory(-1);
                e.Handled = true;
            }
            else if (!SendCombo.IsDropDownOpen && e.Key == Key.Down)
            {
                RecallHistory(+1);
                e.Handled = true;
            }
        };

        // 发送历史右键菜单：清空
        var clearHistory = new MenuItem { Header = "清空发送历史" };
        clearHistory.Click += (_, _) => ClearSendHistory();
        SendCombo.ContextMenu = new ContextMenu();
        SendCombo.ContextMenu.Items.Add(clearHistory);

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
        EditFieldsButton.Click += (_, _) => EditProtocolFields();
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
        RegexCheck.Click += (_, _) =>
        {
            if (_filterEnabled)
            {
                ApplyFilter();
            }
        };
        ClearMatchedButton.Click += (_, _) => ClearMatched();

        // 协议帧解析：任意字段变化即重建解析器
        FrameEnableCheck.Click += (_, _) => ApplyProtocol();
        FrameHeaderEdit.TextChanged += (_, _) => ApplyProtocol();
        FrameTailEdit.TextChanged += (_, _) => ApplyProtocol();
        FrameLengthCombo.SelectionChanged += (_, _) => ApplyProtocol();
        FrameLengthBaseEdit.TextChanged += (_, _) => ApplyProtocol();
        FrameEndianCombo.SelectionChanged += (_, _) => ApplyProtocol();
        FrameChecksumCombo.SelectionChanged += (_, _) => ApplyProtocol();

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
        if (AutoRecord && !_logmgr.IsOpen)
        {
            StartRecord();
        }

        UpdateConnectionUi();
        SendCombo.Focus();
    }

    private void Disconnect() => DisconnectWithMessage("串口已关闭");

    private void DisconnectWithMessage(string? message)
    {
        _monitor.Disconnect();
        if (_logmgr.IsOpen)
        {
            StopRecord();
        }

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

            // 记住最近一帧，供协议字段解析使用
            if (record is { Direction: LogDirection.Rx, Data: not null })
            {
                _latestFrame = record.Data;
                _fieldsDirty = true;
            }

            // 记录到文件（固定文本形式，不受 HEX 显示 / 过滤影响）
            if (_logmgr.IsOpen)
            {
                _logmgr.Write(FormatRecordLine(record));
            }

            // 帧校验失败：追加系统提示（sys 不受暂停影响，不参与过滤）
            if (!record.ChecksumOk && record.Data is not null)
            {
                lines.Add(FormatLine(new LogRecord(record.Time, LogDirection.Sys,
                                                   null, $"帧校验失败: {ToHex(record.Data)}")));
            }

            var text = PayloadText(record);

            // 曲线采集：只取接收行，暂停显示时仍继续采集
            if (record.Direction == LogDirection.Rx && _plotHub.Enabled)
            {
                _plotHub.Feed(text);
            }

            // 应答高亮：发送后收到的第一条 RX 用应答标记
            var isResponse = false;
            if (record.Direction == LogDirection.Rx && _responsePending)
            {
                _responsePending = false;
                isResponse = true;
            }

            var visible = _filter.Visible(text);
            var isMatch = _filter.Mode == FilterModes.Split && _filter.Matched(text).Count > 0;

            // 暂停只冻结 rx/tx 显示，sys 仍实时显示；buffer 继续积累，恢复时全量重建
            if (_paused && record.Direction != LogDirection.Sys)
            {
                continue;
            }

            if (visible)
            {
                lines.Add(FormatLine(record, isResponse));
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

        if (_fieldsDirty)
        {
            MaybeRefreshFields();
        }

        UpdateEmptyHint();

        // 分片 / 错误处理（与 Python 版一致，drain 之后统一处理）
        if (_logmgr.IsOpen)
        {
            _logmgr.Flush(ShardMb, LogDirectory);
            if (_logmgr.Error is not null)
            {
                var err = _logmgr.Error;
                _logmgr.Close();
                SyncRecordButton();
                AddSystem($"记录写入失败：{err}");
                MessageBox.Show(Window.GetWindow(this)!, $"日志写入失败，已停止记录：\n{err}",
                                "记录失败", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
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

    private string FormatLine(LogRecord record, bool response = false)
    {
        var ts = TimestampModes.Format(record.Time, _timestamp);
        var tsPrefix = ts.Length > 0 ? $"[{ts}] " : "";

        if (record.Direction == LogDirection.Sys)
        {
            return $"{tsPrefix}{LogView.SysMark}{record.Text}";
        }

        var mark = record.Direction == LogDirection.Tx
            ? LogView.TxMark
            : response ? LogView.ResponseMark : "";
        var prefix = $"{tsPrefix}{mark}";

        if (_hexView && record.Data is not null)
        {
            return FormatHexDisplay(record.Data, prefix);
        }

        return $"{prefix}{DisplayBody(record.Data)}";
    }

    /// <summary>HEX 显示：每 16 字节一行，右侧 ASCII 对照；首行带前缀，续行对齐。</summary>
    private static string FormatHexDisplay(byte[] data, string prefix)
    {
        var rows = HexText.Rows(data);
        var sb = new StringBuilder();
        for (var i = 0; i < rows.Count; i++)
        {
            if (sb.Length > 0)
            {
                sb.Append('\n');
            }

            var rowPrefix = i == 0 ? prefix : new string(' ', prefix.Length);
            sb.Append(rowPrefix)
              .Append(rows[i].Hex.PadRight(HexText.RowBytes * 3 - 1))
              .Append("  ")
              .Append(rows[i].Ascii);
        }

        return sb.ToString();
    }

    private string DisplayBody(byte[]? data) =>
        data is null ? "" : _encoding.GetString(data);

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
            .Select(r => FormatLine(r))
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
            .Select(r => FormatLine(r))
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
        _latestFrame = null;
        _plotHub.Clear();
        RefreshFields();
        UpdateEmptyHint();
        RaiseStatusChanged();
    }

    /// <summary>主日志区空态提示（有缓存行时隐藏，清空后显示）。</summary>
    private void UpdateEmptyHint() =>
        LogEmptyHint.Visibility = _buffer.Count == 0 ? Visibility.Visible : Visibility.Collapsed;

    // ---------- 记录 ----------

    public void ToggleRecord()
    {
        if (_logmgr.IsOpen)
        {
            StopRecord();
        }
        else
        {
            StartRecord();
        }
    }

    public void StartRecord()
    {
        if (!_logmgr.IsOpen)
        {
            var port = (PortCombo.SelectedItem as PortInfo?)?.PortName ?? "";
            var path = _logmgr.Open(port, LogDirectory);
            if (path is not null)
            {
                AddSystem($"开始记录到: {path}");
            }
            else
            {
                AddSystem($"记录启动失败：{_logmgr.Error}");
                MessageBox.Show(Window.GetWindow(this)!, $"无法创建日志文件：\n{_logmgr.Error}",
                                "记录失败", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }

        SyncRecordButton();
    }

    public void StopRecord()
    {
        if (_logmgr.IsOpen)
        {
            _logmgr.Close();
        }

        SyncRecordButton();
        AddSystem("已停止记录");
    }

    private void SyncRecordButton()
    {
        if (_logmgr.IsOpen)
        {
            RecordButton.Content = "停止记录";
            RecordButton.Tag = "danger";
        }
        else
        {
            RecordButton.Content = "开始记录";
            RecordButton.Tag = null;
        }
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
            CaseCheck.IsChecked == true,
            RegexCheck.IsChecked == true);

        LogText.SetKeywords(_filter.Keywords, _filter.CaseSensitive);
        MatchedText.SetKeywords(_filter.Keywords, _filter.CaseSensitive);
        ReRender();

        MatchedPanel.Visibility = _filter.Mode == FilterModes.Split
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    private void ClearMatched() => MatchedText.ClearAll();

    // ---------- 协议帧解析 ----------

    /// <summary>折叠 / 展开协议面板的详情字段（只留「按帧解析」与折叠按钮）。</summary>
    private void OnToggleProtocolDetailClick(object sender, RoutedEventArgs e)
    {
        var collapsed = ProtocolDetailPanel.Visibility == Visibility.Visible;
        ProtocolDetailPanel.Visibility = collapsed ? Visibility.Collapsed : Visibility.Visible;
        ProtocolFoldButton.Content = collapsed ? "详情 ▾" : "收起 ▴";
    }

    /// <summary>面板显示 / 隐藏：显示时 120ms 淡入，隐藏即时收起（低频交互，不碰日志渲染路径）。</summary>
    private static void SetPanelVisible(FrameworkElement panel, bool visible)
    {
        if (visible)
        {
            panel.BeginAnimation(OpacityProperty, null);
            panel.Opacity = 0;
            panel.Visibility = Visibility.Visible;
            panel.BeginAnimation(OpacityProperty,
                new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(120))
                {
                    EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut },
                });
        }
        else
        {
            panel.BeginAnimation(OpacityProperty, null);
            panel.Opacity = 1;
            panel.Visibility = Visibility.Collapsed;
        }
    }

    private void ApplyProtocol()
    {
        if (FrameEnableCheck.IsChecked != true)
        {
            _monitor.SetFrameParser(null);
            _frameDataOffset = 0;
            _latestFrame = null;
            RefreshFields();
            return;
        }

        // 帧头/帧尾 HEX 非法时按空处理（输入过程中的中间态也不会报错打断）
        var header = SendCodec.ParseHex(FrameHeaderEdit.Text) ?? [];
        var lengthSize = (FrameLengthCombo.SelectedValue as int?) ?? 0;
        _frameDataOffset = header.Length + lengthSize;

        _monitor.SetFrameParser(new FrameParser
        {
            Header = header,
            Tail = SendCodec.ParseHex(FrameTailEdit.Text) ?? [],
            LengthSize = lengthSize,
            LengthBase = int.TryParse(FrameLengthBaseEdit.Text.Trim(), out var lb) ? lb : 0,
            BigEndian = (FrameEndianCombo.SelectedValue as bool?) ?? true,
            Checksum = FrameParser.ParseChecksum(FrameChecksumCombo.SelectedValue as string),
        });

        RefreshFields();
    }

    /// <summary>编辑协议字段（名称 / 偏移 / 类型 / 系数）。</summary>
    private void EditProtocolFields()
    {
        var dialog = new ProtocolFieldDialog(_protocolFields) { Owner = Window.GetWindow(this) };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        _protocolFields = dialog.Result;
        if (_protocolFields.Count > 0)
        {
            FieldsPanel.Visibility = Visibility.Visible;
        }

        RefreshFields();
        AddSystem(_protocolFields.Count > 0
            ? $"协议字段已设为 {_protocolFields.Count} 个"
            : "协议字段已清空");
    }

    /// <summary>
    /// 限速刷新字段表：面板不可见时不解码；可见时最多每 150ms 重建一次行。
    /// （ItemsControl 每次赋 ItemsSource 都会重建容器，高频帧下必须节流。）
    /// </summary>
    private void MaybeRefreshFields()
    {
        if (FieldsPanel.Visibility != Visibility.Visible)
        {
            return;
        }

        var now = Environment.TickCount64;
        if (now - _lastFieldsRefreshTicks < 150)
        {
            return;
        }

        _lastFieldsRefreshTicks = now;
        RefreshFields();
    }

    /// <summary>用最新一帧刷新字段表（按帧解析关闭 / 无数据时给提示）。</summary>
    private void RefreshFields()
    {
        _fieldsDirty = false;

        if (_protocolFields.Count == 0)
        {
            FieldsList.ItemsSource = null;
            FieldsHint.Text = "（未定义字段，点「字段...」添加）";
            return;
        }

        if (FrameEnableCheck.IsChecked != true)
        {
            FieldsList.ItemsSource = null;
            FieldsHint.Text = "（按帧解析未开启）";
            return;
        }

        if (_latestFrame is null)
        {
            FieldsList.ItemsSource = null;
            FieldsHint.Text = "（等待数据）";
            return;
        }

        var values = ProtocolDecoder.Decode(_latestFrame, _frameDataOffset, _protocolFields);
        FieldsList.ItemsSource = values;
        FieldsHint.Text = $"共 {values.Count} 个字段 · 帧长 {_latestFrame.Length} 字节";
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

    /// <summary>发送当前输入框内容（全局快捷键 Ctrl+Enter 用）。</summary>
    public void SendCurrentInput() => SendRaw();

    private void SendRaw()
    {
        var text = SendCombo.Text;
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        if (SendContent(text, addHistory: true))
        {
            AddSendHistory(text);
        }
    }

    /// <summary>发送命令辅助里的命令内容（不写入发送历史）。</summary>
    public void SendCommandContent(string content)
    {
        if (string.IsNullOrEmpty(content))
        {
            AddSystem("命令内容为空");
            return;
        }

        SendContent(content, addHistory: false);
    }

    /// <summary>
    /// 发送原始字节（文件下发用）：不做 HEX/换行/校验处理，原样发送并回显、计 TX。
    /// 未连接或发送失败返回 false。
    /// </summary>
    public bool SendRawBytes(byte[] data)
    {
        if (data.Length == 0)
        {
            return true;
        }

        if (!_monitor.IsConnected)
        {
            return false;
        }

        if (_monitor.Send(data))
        {
            _txBytes += data.Length;
            _pending.Enqueue(new LogRecord(DateTime.Now, LogDirection.Tx, data, null));
            _responsePending = true;
            RaiseStatusChanged();
            return true;
        }

        return false;
    }

    /// <summary>按当前 HEX / 换行 / 编码设置编码并发送；返回是否已提交。</summary>
    private bool SendContent(string text, bool addHistory)
    {
        byte[] data;
        if (HexSendCheck.IsChecked == true)
        {
            var parsed = SendCodec.ParseHex(text);
            if (parsed is null)
            {
                AddSystem("HEX 格式无效（示例：01 03 00 0A）");
                return false;
            }

            data = parsed;
        }
        else
        {
            data = SendCodec.ParseEscaped(text, _encoding);
        }

        // 发送自动算校验：追加在换行之前
        var checksumKey = ChecksumCombo.SelectedValue as string ?? ChecksumKeys.None;
        if (checksumKey != ChecksumKeys.None)
        {
            data = [.. data, .. FrameParser.ChecksumBytes(FrameParser.ParseChecksum(checksumKey), data)];
        }

        // 文本模式追加换行（HEX 模式不加，且换行永远在校验之后）
        if (HexSendCheck.IsChecked != true)
        {
            var newline = NewlineCombo.SelectedValue as string ?? "";
            if (newline.Length > 0)
            {
                data = [.. data, .. _encoding.GetBytes(newline)];
            }
        }

        if (!_monitor.IsConnected)
        {
            AddSystem("串口未打开，无法发送");
            return false;
        }

        if (_monitor.Send(data))
        {
            _txBytes += data.Length;
            _pending.Enqueue(new LogRecord(DateTime.Now, LogDirection.Tx, data, null));
            _responsePending = true;
            RaiseStatusChanged();
            return true;
        }

        return false;
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

        _histIdx = -1;
    }

    /// <summary>上下键回填发送历史：-1 更早（上），+1 更新（下）。</summary>
    private void RecallHistory(int direction)
    {
        var count = SendCombo.Items.Count;
        if (count == 0)
        {
            return;
        }

        int next;
        if (_histIdx == -1)
        {
            // 从编辑态进入浏览：上键从最新一条开始，下键无操作
            next = direction < 0 ? count - 1 : -1;
            if (next < 0)
            {
                return;
            }
        }
        else
        {
            next = _histIdx + direction;
        }

        if (next < 0)
        {
            return;
        }

        if (next >= count)
        {
            _histIdx = -1;
            SendCombo.Text = "";
            return;
        }

        _histIdx = next;
        SendCombo.Text = SendCombo.Items[_histIdx].ToString() ?? "";
    }

    private void ClearSendHistory()
    {
        SendCombo.Items.Clear();
        _histIdx = -1;
        AddSystem("发送历史已清空");
    }

    private void AddSystem(string text) =>
        _pending.Enqueue(new LogRecord(DateTime.Now, LogDirection.Sys, null, text));

    /// <summary>主窗口全局反馈：写入当前会话的系统日志（供命令辅助等模块调用）。</summary>
    public void AddSystemText(string text) => AddSystem(text);

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
        _rateTimer.Stop();
        _logmgr.Close();
        _monitor.Disconnect();
    }

    /// <summary>供后续里程碑（日志录制 / 过滤）复用：当前显示区控件。</summary>
    public LogView LogControl => LogText;

    /// <summary>按当前主题刷新日志着色颜色（时间戳 / 发送 / 系统 / 高亮）。</summary>
    public void ApplyThemeColors()
    {
        foreach (var log in new[] { LogText, MatchedText })
        {
            log.ApplyTheme();
            log.TimestampBrush = ThemeService.GetBrush("Brush.LogTimestamp");
            log.TxBrush = ThemeService.GetBrush("Brush.LogTx");
            log.SysBrush = ThemeService.GetBrush("Brush.LogSys");
            log.ResponseBrush = ThemeService.GetBrush("Brush.Response");
            log.HighlightBackground = ThemeService.GetBrush("Brush.HighlightBg");
            log.HighlightForeground = ThemeService.GetBrush("Brush.HighlightFg");
        }
    }

    /// <summary>设置日志等宽字体（主日志区 + 命中分栏）。</summary>
    public void SetLogFontFamily(string family)
    {
        var font = new System.Windows.Media.FontFamily(family);
        LogText.FontFamily = font;
        MatchedText.FontFamily = font;
    }
}

/// <summary>一条待显示 / 已缓存的日志。</summary>
public sealed record LogRecord(
    DateTime Time,
    LogDirection Direction,
    byte[]? Data,
    string? Text,
    bool ChecksumOk = true);
