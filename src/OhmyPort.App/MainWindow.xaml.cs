using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using Microsoft.Win32;
using OhmyPort.App.Views;
using OhmyPort.Core;
using OhmyPort.Core.Models;
using WinForms = System.Windows.Forms;

namespace OhmyPort.App;

public partial class MainWindow : Window, INotifyPropertyChanged
{
    private readonly List<SessionView> _sessions = [];
    private readonly ConfigService _configService = new();
    private readonly DispatcherTimer _cycleTimer;
    private readonly DispatcherTimer _autoThemeTimer;
    private WinForms.NotifyIcon? _notifyIcon;
    private AppConfig _config = new();
    private bool _cycleEnabled;
    private int _cycleInterval = 1000;
    private int _cycleIndex;
    private bool _forceQuit;
    private CycleDialog? _cycleDialog;

    public MainWindow()
    {
        InitializeComponent();
        Title = $"{AppInfo.Name} v{AppInfo.Version}";
        PreviewKeyDown += OnPreviewKeyDown;
        SessionTabs.SelectionChanged += (_, _) =>
        {
            SyncMenuState();
            RefreshStatusBar();
        };

        _cycleTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(_cycleInterval),
        };
        _cycleTimer.Tick += (_, _) => OnCycleTick();

        _config = _configService.Load();

        // 主题
        ThemeService.Apply(_config.Theme);
        SyncThemeMenu();
        ThemeService.ThemeChanged += OnThemeChanged;
        _autoThemeTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromSeconds(2),
        };
        _autoThemeTimer.Tick += (_, _) => ThemeService.RefreshIfAuto();
        _autoThemeTimer.Start();

        // 菜单状态（记录 / 托盘 / 关闭确认）
        AutoRecordMenu.IsChecked = _config.AutoRecord;
        TrayMenu.IsChecked = _config.CloseBehavior == "tray";
        CloseConfirmMenu.IsChecked = _config.CloseConfirm;

        var count = Math.Max(1, _config.Sessions.Count);
        for (var i = 0; i < count; i++)
        {
            AddSession();
        }

        for (var i = 0; i < _sessions.Count && i < _config.Sessions.Count; i++)
        {
            ApplyRememberedState(_sessions[i], _config.Sessions[i]);
        }

        // 全局：自动换行 + 日志设置 + 主题着色
        WrapMenu.IsChecked = _config.WrapEnabled;
        ApplyGlobalSettings();

        RebuildCommandTabs();
        SetupTray();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>定时循环发送是否启用（发送辅助面板指示绑定）。</summary>
    public bool CycleEnabled
    {
        get => _cycleEnabled;
        private set
        {
            if (_cycleEnabled != value)
            {
                _cycleEnabled = value;
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(CycleEnabled)));
            }
        }
    }

    /// <summary>当前日志保存目录（未自定义则默认数据目录下 Logs）。</summary>
    private string LogDirPath =>
        string.IsNullOrEmpty(_config.LogDir) ? AppPaths.DefaultLogDir : _config.LogDir;

    /// <summary>把全局设置（换行 / 日志目录 / 分片 / 自动记录 / 主题着色）同步到所有会话。</summary>
    private void ApplyGlobalSettings()
    {
        foreach (var session in _sessions)
        {
            session.WrapEnabled = _config.WrapEnabled;
            session.LogDirectory = LogDirPath;
            session.ShardMb = _config.ShardMb;
            session.AutoRecord = _config.AutoRecord;
            session.ApplyThemeColors();
        }
    }

    private void SyncThemeMenu()
    {
        ThemeAutoMenu.IsChecked = ThemeService.ThemeKey == ThemeService.Auto;
        ThemeBlackMenu.IsChecked = ThemeService.ThemeKey == ThemeService.Black;
        ThemeDayMenu.IsChecked = ThemeService.ThemeKey == ThemeService.Day;
        ThemeEyeMenu.IsChecked = ThemeService.ThemeKey == ThemeService.Eye;
    }

    private void OnThemeChanged()
    {
        SyncThemeMenu();
        foreach (var session in _sessions)
        {
            session.ApplyThemeColors();
        }
    }

    private void OnThemeClick(object sender, RoutedEventArgs e)
    {
        if (sender is MenuItem { Tag: string key })
        {
            _config.Theme = key;
            ThemeService.Apply(key);
            _configService.Save(_config);
        }
    }

    private static void ApplyRememberedState(SessionView session, SessionConfig remembered)
    {
        if (!string.IsNullOrEmpty(remembered.Port))
        {
            session.RememberedPort = remembered.Port;
        }

        if (!string.IsNullOrEmpty(remembered.Baud))
        {
            session.BaudText = remembered.Baud;
        }

        if (remembered.FontSize > 0)
        {
            session.SetFontSize(remembered.FontSize);
        }

        session.ApplyRememberedFilter(
            remembered.FilterKeywords,
            remembered.FilterMode,
            remembered.FilterCase,
            remembered.FilterEnabled);
    }

    private SessionView? ActiveSession =>
        (SessionTabs.SelectedItem as TabItem)?.Content as SessionView;

    // ---------- 会话管理 ----------

    private void AddSession()
    {
        var session = new SessionView
        {
            Index = _sessions.Count,
            LogDirectory = LogDirPath,
            ShardMb = _config.ShardMb,
            AutoRecord = _config.AutoRecord,
            WrapEnabled = _config.WrapEnabled,
        };
        session.TitleChanged += (_, _) => RefreshStatusBar();
        session.StatusChanged += (_, _) =>
        {
            if (ReferenceEquals(session, ActiveSession))
            {
                RefreshStatusBar();
            }
        };

        _sessions.Add(session);
        SessionTabs.Items.Add(new TabItem { Header = session, Content = session });
        SessionTabs.SelectedIndex = SessionTabs.Items.Count - 1;
        session.ApplyThemeColors();
        SyncMenuState();
        RefreshStatusBar();
    }

    private void CloseSession(SessionView session)
    {
        if (_sessions.Count <= 1)
        {
            MessageBox.Show(this, "至少保留一个串口标签页", "串口",
                            MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        session.Shutdown();
        _sessions.Remove(session);

        var tab = SessionTabs.Items.OfType<TabItem>()
            .FirstOrDefault(t => ReferenceEquals(t.Content, session));
        if (tab is not null)
        {
            SessionTabs.Items.Remove(tab);
        }

        // 重新编号，标题里的「串口N」跟着变
        for (var i = 0; i < _sessions.Count; i++)
        {
            _sessions[i].Index = i;
            _sessions[i].RefreshTitle();
        }

        SyncMenuState();
        RefreshStatusBar();
    }

    private void OnPreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (Keyboard.Modifiers != ModifierKeys.Control)
        {
            return;
        }

        switch (e.Key)
        {
            case Key.T:
                AddSession();
                e.Handled = true;
                break;
            case Key.S:
                ActiveSession?.SaveLog();
                e.Handled = true;
                break;
            case Key.OemPlus:          // Ctrl+= / Ctrl++（= 与 + 共用一键）
                ActiveSession?.ZoomIn();
                e.Handled = true;
                break;
            case Key.OemMinus:         // Ctrl+-
                ActiveSession?.ZoomOut();
                e.Handled = true;
                break;
            case Key.D0:               // Ctrl+0
                ActiveSession?.ResetZoom();
                e.Handled = true;
                break;
        }
    }

    // ---------- 菜单 ----------

    private void OnNewSessionClick(object sender, RoutedEventArgs e) => AddSession();

    private void OnCloseCurrentSessionClick(object sender, RoutedEventArgs e)
    {
        if (ActiveSession is { } session)
        {
            CloseSession(session);
        }
    }

    private void OnCloseTabClick(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: SessionView session })
        {
            CloseSession(session);
        }
    }

    private void OnToggleParamsClick(object sender, RoutedEventArgs e)
    {
        if (ActiveSession is { } session)
        {
            session.ParamsVisible = ParamsMenu.IsChecked;
        }
    }

    private void OnToggleSendClick(object sender, RoutedEventArgs e)
    {
        if (ActiveSession is { } session)
        {
            session.SendVisible = SendMenu.IsChecked;
        }
    }

    private void OnToggleHexViewClick(object sender, RoutedEventArgs e)
    {
        if (ActiveSession is { } session)
        {
            session.HexView = HexViewMenu.IsChecked;
        }
    }

    private void OnToggleFixedClick(object sender, RoutedEventArgs e)
    {
        if (ActiveSession is { } session)
        {
            session.FixedView = FixedMenu.IsChecked;
        }
    }

    private void OnSaveLogClick(object sender, RoutedEventArgs e) => ActiveSession?.SaveLog();

    private void OnToggleFilterClick(object sender, RoutedEventArgs e)
    {
        if (ActiveSession is { } session)
        {
            session.FilterVisible = FilterMenu.IsChecked;
        }
    }

    private void OnToggleWrapClick(object sender, RoutedEventArgs e)
    {
        _config.WrapEnabled = WrapMenu.IsChecked;
        foreach (var session in _sessions)
        {
            session.WrapEnabled = _config.WrapEnabled;
        }

        _configService.Save(_config);
    }

    private void OnZoomInClick(object sender, RoutedEventArgs e) => ActiveSession?.ZoomIn();

    private void OnZoomOutClick(object sender, RoutedEventArgs e) => ActiveSession?.ZoomOut();

    private void OnResetZoomClick(object sender, RoutedEventArgs e) => ActiveSession?.ResetZoom();

    private void OnToggleSendAssistClick(object sender, RoutedEventArgs e)
    {
        SendAssistPanel.Visibility = SendAssistMenu.IsChecked ? Visibility.Visible : Visibility.Collapsed;
    }

    private void OnExitClick(object sender, RoutedEventArgs e) => Close();

    private void OnAboutClick(object sender, RoutedEventArgs e) =>
        MessageBox.Show(
            this,
            $"{AppInfo.Name} v{AppInfo.Version}\n\n作者：{AppInfo.Author}\n项目主页：{AppInfo.Url}\n\n" +
            "C# / WPF 版本（.NET 10）。",
            "关于", MessageBoxButton.OK, MessageBoxImage.Information);

    // ---------- 日志记录设置（M8） ----------

    private void OnOpenLogDirClick(object sender, RoutedEventArgs e)
    {
        try
        {
            Directory.CreateDirectory(LogDirPath);
            Process.Start(new ProcessStartInfo("explorer.exe", LogDirPath) { UseShellExecute = true });
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            MessageBox.Show(this, ex.Message, "打开失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void OnToggleAutoRecordClick(object sender, RoutedEventArgs e)
    {
        _config.AutoRecord = AutoRecordMenu.IsChecked;
        foreach (var session in _sessions)
        {
            session.AutoRecord = _config.AutoRecord;
        }

        _configService.Save(_config);
    }

    private void OnChooseLogDirClick(object sender, RoutedEventArgs e)
    {
        using var dialog = new WinForms.FolderBrowserDialog
        {
            Description = "选择日志保存目录",
            SelectedPath = LogDirPath,
            UseDescriptionForTitle = true,
        };
        if (dialog.ShowDialog() != WinForms.DialogResult.OK)
        {
            return;
        }

        _config.LogDir = dialog.SelectedPath;
        foreach (var session in _sessions)
        {
            session.LogDirectory = dialog.SelectedPath;
        }

        _configService.Save(_config);
        ActiveSession?.AddSystemText($"日志保存目录已设为: {dialog.SelectedPath}");
    }

    private void OnSetShardSizeClick(object sender, RoutedEventArgs e)
    {
        var dialog = new NumberInputDialog("日志分片大小", "每个日志文件最大大小（MB）：", _config.ShardMb, 1, 1024)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        _config.ShardMb = dialog.Value;
        foreach (var session in _sessions)
        {
            session.ShardMb = dialog.Value;
        }

        _configService.Save(_config);
        ActiveSession?.AddSystemText($"日志分片大小已设为 {dialog.Value} MB");
    }

    private void OnSetLogRetentionClick(object sender, RoutedEventArgs e)
    {
        var dialog = new ComboSelectDialog("日志保留策略", "保留时长",
                                           LogRetention.Options.Select(o => (o.Label, o.Key)).ToArray(),
                                           _config.LogRetention,
                                           "到期自动清理旧日志文件（仅 .txt 日志）。「无限制」表示不清理。")
        {
            Owner = this,
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        _config.LogRetention = dialog.SelectedKey;
        _configService.Save(_config);
        CleanOldLogs();
    }

    private void CleanOldLogs() =>
        OhmyPort.Core.Logging.LogManager.CleanOldLogs(LogDirPath, _config.LogRetention);

    // ---------- 托盘 / 关闭行为（M9） ----------

    private void SetupTray()
    {
        _notifyIcon = new WinForms.NotifyIcon
        {
            Icon = System.Drawing.Icon.ExtractAssociatedIcon(
                System.IO.Path.Combine(AppContext.BaseDirectory, "OhmyPort.exe")) ??
                   System.Drawing.SystemIcons.Application,
            Text = AppInfo.Name,
            Visible = true,
            ContextMenuStrip = new WinForms.ContextMenuStrip(),
        };
        _notifyIcon.ContextMenuStrip.Items.Add("显示主窗口", null, (_, _) => ShowFromTray());
        _notifyIcon.ContextMenuStrip.Items.Add("退出", null, (_, _) => QuitFromTray());
        _notifyIcon.DoubleClick += (_, _) => ShowFromTray();
    }

    private void ShowFromTray()
    {
        Show();
        WindowState = WindowState.Normal;
        Activate();
    }

    private void QuitFromTray()
    {
        _forceQuit = true;
        Close();
    }

    private void OnToggleTrayClick(object sender, RoutedEventArgs e)
    {
        _config.CloseBehavior = TrayMenu.IsChecked ? "tray" : "exit";
        _configService.Save(_config);
    }

    private void OnToggleCloseConfirmClick(object sender, RoutedEventArgs e)
    {
        _config.CloseConfirm = CloseConfirmMenu.IsChecked;
        _configService.Save(_config);
    }

    // ---------- 字体（M9） ----------

    private void OnChooseFontClick(object sender, RoutedEventArgs e)
    {
        var dialog = new ComboSelectDialog(
            "日志字体", "等宽字体",
            [("系统默认等宽", "default"), ("Consolas", "Consolas"),
             ("Cascadia Code", "Cascadia Code"), ("JetBrains Mono", "JetBrains Mono")],
            _config.FontFamily, "字体未安装时会自动回退到系统默认等宽字体。")
        {
            Owner = this,
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        _config.FontFamily = dialog.SelectedKey;
        ApplyLogFont();
        _configService.Save(_config);
    }

    private void ApplyLogFont()
    {
        var family = _config.FontFamily;
        if (family is "" or "default" ||
            !System.Windows.Media.Fonts.SystemFontFamilies.Any(f =>
                string.Equals(f.Source, family, StringComparison.OrdinalIgnoreCase)))
        {
            family = "Consolas";
        }

        foreach (var session in _sessions)
        {
            session.SetLogFontFamily(family);
        }
    }

    // ---------- 背景皮肤（M9） ----------

    private void OnOpenBackgroundClick(object sender, RoutedEventArgs e)
    {
        var dialog = new BackgroundDialog(
            _config.BgDir, _config.BgImage, _config.BgBlur, _config.BgEnabled)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        _config.BgDir = dialog.BgDir;
        _config.BgImage = dialog.BgImage;
        _config.BgBlur = dialog.BgBlur;
        _config.BgEnabled = dialog.BgEnabled;
        ApplyBackground();
        _configService.Save(_config);
    }

    private void ApplyBackground()
    {
        BgLayer.Source = null;
        BgLayer.Visibility = Visibility.Collapsed;
        BgBlurEffect.Radius = 0;

        if (!_config.BgEnabled || string.IsNullOrEmpty(_config.BgImage))
        {
            return;
        }

        var src = System.IO.Path.Combine(_config.BgDir, _config.BgImage);
        if (!File.Exists(src))
        {
            return;
        }

        try
        {
            BgLayer.Source = new System.Windows.Media.Imaging.BitmapImage(new Uri(src));
            // 模糊强度映射：0..50 → 0..30 像素
            BgBlurEffect.Radius = _config.BgBlur > 0 ? _config.BgBlur * 0.6 : 0;
            BgLayer.Visibility = Visibility.Visible;
        }
        catch
        {
            BgLayer.Source = null;
            BgLayer.Visibility = Visibility.Collapsed;
        }
    }

    // ---------- 发送辅助：命令页 / 命令 ----------

    private void OnAddCommandClick(object sender, RoutedEventArgs e) => AddCommand();

    private void OnAddPageClick(object sender, RoutedEventArgs e)
    {
        _config.Pages.Add($"第{_config.Pages.Count + 1}页");
        CommandsChanged();
    }

    private void OnOpenCycleDialogClick(object sender, RoutedEventArgs e)
    {
        _cycleDialog ??= new CycleDialog(
            _cycleEnabled, _cycleInterval, _config.Commands,
            onEnableChanged: SetCycleEnabled,
            onIntervalChanged: SetCycleInterval,
            onCommandCycleChanged: SetCommandCycle);
        _cycleDialog.Refresh(_cycleEnabled, _cycleInterval, _config.Commands);
        _cycleDialog.Owner = this;
        _cycleDialog.Show();
        _cycleDialog.Activate();
    }

    private void AddCommand(int? editIndex = null)
    {
        var editing = editIndex is { } idx && idx >= 0 && idx < _config.Commands.Count
            ? _config.Commands[idx]
            : null;

        var dialog = new CommandEditDialog(
            _config.Pages,
            page => _config.Commands.Count(c => c.Page == page),
            editing is null ? "添加命令" : "编辑命令",
            editing?.Name,
            editing?.Content,
            editing?.Page ?? 0)
        {
            Owner = this,
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var name = dialog.CommandName;
        var content = dialog.CommandContent;
        if (name.Length == 0 && content.Length == 0)
        {
            return;
        }

        var page = dialog.SelectedPage;
        if (page == -1)
        {
            page = _config.Pages.Count;
            _config.Pages.Add($"第{page + 1}页");
        }
        else if (_config.Commands.Count(c => c.Page == page) >= 8)
        {
            MessageBox.Show(this, "该页已满（每页最多 8 个），请选择其它页或新建页",
                            "添加命令", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (editing is null)
        {
            _config.Commands.Add(new CommandItem
            {
                Name = name.Length > 0 ? name : $"命令{_config.Commands.Count + 1}",
                Content = content,
                Cycle = false,
                Page = page,
            });
        }
        else
        {
            editing.Name = name.Length > 0 ? name : editing.Name;
            editing.Content = content;
            editing.Page = page;
        }

        CommandsChanged();
    }

    private void EditCommand(int index)
    {
        if (index >= 0 && index < _config.Commands.Count)
        {
            AddCommand(index);
        }
    }

    private void DeleteCommand(int index)
    {
        if (index < 0 || index >= _config.Commands.Count)
        {
            return;
        }

        var name = _config.Commands[index].Name;
        if (MessageBox.Show(this, $"确定删除命令「{name}」吗？", "删除命令",
                            MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
        {
            return;
        }

        _config.Commands.RemoveAt(index);
        CommandsChanged();
    }

    private void SendCommand(int index)
    {
        if (index < 0 || index >= _config.Commands.Count)
        {
            return;
        }

        var content = _config.Commands[index].Content;
        if (string.IsNullOrEmpty(content))
        {
            ActiveSession?.AddSystemText("命令内容为空");
            return;
        }

        ActiveSession?.SendCommandContent(content);
    }

    private void AddPage() => OnAddPageClick(this, new RoutedEventArgs());

    private void RenamePage(int index)
    {
        if (index < 0 || index >= _config.Pages.Count)
        {
            return;
        }

        var dialog = new CommandEditDialog(_config.Pages, _ => 0, "重命名页",
                                           name: _config.Pages[index], pageOnly: true)
        {
            Owner = this,
        };
        if (dialog.ShowDialog() == true && dialog.CommandName.Length > 0)
        {
            _config.Pages[index] = dialog.CommandName;
            CommandsChanged();
        }
    }

    private void DeletePage(int index)
    {
        if (index < 0 || index >= _config.Pages.Count)
        {
            return;
        }

        if (_config.Pages.Count <= 1)
        {
            ActiveSession?.AddSystemText("至少保留一个页");
            return;
        }

        var count = _config.Commands.Count(c => c.Page == index);
        var msg = $"确定删除页「{_config.Pages[index]}」吗？";
        if (count > 0)
        {
            msg += $"\n该页有 {count} 条命令，将一并删除。";
        }

        if (MessageBox.Show(this, msg, "删除页", MessageBoxButton.YesNo, MessageBoxImage.Warning)
            != MessageBoxResult.Yes)
        {
            return;
        }

        _config.Pages.RemoveAt(index);
        _config.Commands.RemoveAll(c => c.Page == index);
        foreach (var cmd in _config.Commands)
        {
            if (cmd.Page > index)
            {
                cmd.Page--;
            }
        }

        CommandsChanged();
    }

    private void RebuildCommandTabs()
    {
        CommandTabs.Items.Clear();
        for (var p = 0; p < _config.Pages.Count; p++)
        {
            var page = new CommandPageContent(_config.Commands, p,
                send: SendCommand, edit: EditCommand, delete: DeleteCommand);
            var tabItem = new TabItem
            {
                Header = _config.Pages[p],
                Content = page,
            };
            tabItem.ContextMenu = BuildPageContextMenu(p);
            CommandTabs.Items.Add(tabItem);
        }

        // Clear 后 SelectedIndex 会变 -1，需手动选中第一个，否则各页内容不渲染
        if (CommandTabs.Items.Count > 0)
        {
            CommandTabs.SelectedIndex = 0;
        }
    }

    private ContextMenu BuildPageContextMenu(int pageIndex)
    {
        var menu = new ContextMenu();
        var addPage = new MenuItem { Header = "新增页" };
        addPage.Click += (_, _) => AddPage();
        menu.Items.Add(addPage);

        if (pageIndex >= 0)
        {
            var rename = new MenuItem { Header = "重命名页" };
            rename.Click += (_, _) => RenamePage(pageIndex);
            menu.Items.Add(rename);

            var delete = new MenuItem { Header = "删除该页" };
            delete.Click += (_, _) => DeletePage(pageIndex);
            menu.Items.Add(delete);
        }

        return menu;
    }

    private void CommandsChanged()
    {
        RebuildCommandTabs();
        _cycleDialog?.Refresh(_cycleEnabled, _cycleInterval, _config.Commands);
        _configService.Save(_config);
    }

    // ---------- 定时循环发送 ----------

    private void OnCycleTick()
    {
        if (ActiveSession is not { } session || !session.IsConnected)
        {
            return;
        }

        var checkedCommands = _config.Commands
            .Where(c => c.Cycle && c.Content.Length > 0)
            .ToList();
        if (checkedCommands.Count == 0)
        {
            return;
        }

        var index = _config.Commands.IndexOf(checkedCommands[_cycleIndex % checkedCommands.Count]);
        _cycleIndex++;
        if (index >= 0)
        {
            session.SendCommandContent(_config.Commands[index].Content);
        }
    }

    private void SetCycleEnabled(bool enabled)
    {
        CycleEnabled = enabled;
        if (enabled)
        {
            _cycleIndex = 0;
            _cycleTimer.Interval = TimeSpan.FromMilliseconds(_cycleInterval);
            _cycleTimer.Start();
        }
        else
        {
            _cycleTimer.Stop();
        }
    }

    private void SetCycleInterval(int ms)
    {
        _cycleInterval = ms;
        if (_cycleEnabled)
        {
            _cycleTimer.Interval = TimeSpan.FromMilliseconds(ms);
        }
    }

    private void SetCommandCycle(int index, bool checkedState)
    {
        if (index >= 0 && index < _config.Commands.Count)
        {
            _config.Commands[index].Cycle = checkedState;
            _configService.Save(_config);
        }
    }

    // ---------- 配置导入 / 导出 ----------

    private void OnExportConfigClick(object sender, RoutedEventArgs e)
    {
        SaveConfig();
        var dialog = new SaveFileDialog
        {
            Title = "导出配置",
            Filter = "JSON 文件 (*.json)|*.json",
            FileName = "ohmyport_config.json",
        };
        if (dialog.ShowDialog(this) != true)
        {
            return;
        }

        try
        {
            File.WriteAllText(dialog.FileName,
                JsonSerializer.Serialize(_config, AppConfig.JsonOptions));
            ActiveSession?.AddSystemText($"配置已导出: {dialog.FileName}");
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            MessageBox.Show(this, ex.Message, "导出失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void OnImportConfigClick(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "导入配置",
            Filter = "JSON 文件 (*.json)|*.json",
        };
        if (dialog.ShowDialog(this) != true)
        {
            return;
        }

        AppConfig imported;
        try
        {
            imported = JsonSerializer.Deserialize<AppConfig>(
                File.ReadAllText(dialog.FileName), AppConfig.JsonOptions) ?? new AppConfig();
            imported.Normalize();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            MessageBox.Show(this, $"无法读取配置文件：\n{ex.Message}", "导入失败",
                            MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _config = imported;
        RebuildCommandTabs();

        // 会话数对齐
        var target = Math.Max(1, _config.Sessions.Count);
        while (_sessions.Count < target)
        {
            AddSession();
        }

        while (_sessions.Count > target)
        {
            CloseSession(_sessions[^1]);
        }

        for (var i = 0; i < _sessions.Count && i < _config.Sessions.Count; i++)
        {
            ApplyRememberedState(_sessions[i], _config.Sessions[i]);
        }

        // 全局设置对齐
        WrapMenu.IsChecked = _config.WrapEnabled;
        AutoRecordMenu.IsChecked = _config.AutoRecord;
        TrayMenu.IsChecked = _config.CloseBehavior == "tray";
        CloseConfirmMenu.IsChecked = _config.CloseConfirm;
        ThemeService.Apply(_config.Theme);
        SyncThemeMenu();
        ApplyGlobalSettings();
        ApplyLogFont();
        ApplyBackground();

        _configService.Save(_config);
        ActiveSession?.AddSystemText($"配置已导入: {dialog.FileName}");
    }

    // ---------- 状态 ----------

    private void SyncMenuState()
    {
        WrapMenu.IsChecked = _config.WrapEnabled;
        SendAssistMenu.IsChecked = SendAssistPanel.Visibility == Visibility.Visible;

        if (ActiveSession is not { } session)
        {
            ParamsMenu.IsChecked = false;
            FilterMenu.IsChecked = false;
            SendMenu.IsChecked = true;
            HexViewMenu.IsChecked = false;
            FixedMenu.IsChecked = false;
            return;
        }

        ParamsMenu.IsChecked = session.ParamsVisible;
        FilterMenu.IsChecked = session.FilterVisible;
        SendMenu.IsChecked = session.SendVisible;
        HexViewMenu.IsChecked = session.HexView;
        FixedMenu.IsChecked = session.FixedView;
    }

    private void RefreshStatusBar()
    {
        if (ActiveSession is not { } session)
        {
            StatusLabel.Text = "就绪";
            SessionCountLabel.Text = "";
            return;
        }

        StatusLabel.Text = session.StatusText;
        SessionCountLabel.Text = $"{_sessions.Count} 个会话";
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        // 托盘退出（_forceQuit）直接放行
        if (_forceQuit)
        {
            base.OnClosing(e);
            return;
        }

        var toTray = _config.CloseBehavior == "tray";

        if (_config.CloseConfirm)
        {
            var dialog = new CloseConfirmDialog { Owner = this };
            if (dialog.ShowDialog() == true)
            {
                toTray = dialog.ToTray;
                if (dialog.DoNotAskAgain)
                {
                    _config.CloseConfirm = false;
                    _config.CloseBehavior = toTray ? "tray" : "exit";
                    TrayMenu.IsChecked = toTray;
                    CloseConfirmMenu.IsChecked = false;
                    _configService.Save(_config);
                }
            }
            else
            {
                // 用户直接关闭了对话框 → 取消关闭
                e.Cancel = true;
                return;
            }
        }

        if (toTray)
        {
            e.Cancel = true;
            Hide();
            _notifyIcon?.ShowBalloonTip(2000, AppInfo.Name, "已最小化到托盘，双击图标恢复",
                                        WinForms.ToolTipIcon.Info);
            return;
        }

        base.OnClosing(e);
    }

    protected override void OnClosed(EventArgs e)
    {
        _cycleTimer.Stop();
        _autoThemeTimer.Stop();
        _notifyIcon?.Dispose();
        SaveConfig();
        foreach (var session in _sessions)
        {
            session.Shutdown();
        }

        base.OnClosed(e);
    }

    private void SaveConfig()
    {
        _config.WrapEnabled = WrapMenu.IsChecked;
        _config.Sessions = _sessions
            .Select(s => new SessionConfig
            {
                Port = s.SelectedPort,
                Baud = s.BaudText,
                FontSize = (int)Math.Round(s.FontSizeValue),
                CustomBauds = [],
                FilterKeywords = s.FilterKeywordsText,
                FilterMode = s.FilterModeKey,
                FilterCase = s.FilterCaseSensitive,
                FilterEnabled = s.FilterEnabledState,
            })
            .ToList();

        _configService.Save(_config);
    }
}
