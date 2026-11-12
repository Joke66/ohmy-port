using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using OhmyPort.App.Views;
using OhmyPort.Core;
using OhmyPort.Core.Models;

namespace OhmyPort.App;

public partial class MainWindow : Window
{
    private readonly List<SessionView> _sessions = [];
    private readonly ConfigService _configService = new();
    private AppConfig _config = new();

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

        _config = _configService.Load();
        var count = Math.Max(1, _config.Sessions.Count);
        for (var i = 0; i < count; i++)
        {
            AddSession();
        }

        for (var i = 0; i < _sessions.Count && i < _config.Sessions.Count; i++)
        {
            ApplyRememberedState(_sessions[i], _config.Sessions[i]);
        }

        // 全局：自动换行
        WrapMenu.IsChecked = _config.WrapEnabled;
        foreach (var session in _sessions)
        {
            session.WrapEnabled = _config.WrapEnabled;
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
        var session = new SessionView { Index = _sessions.Count };
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

    private void OnExitClick(object sender, RoutedEventArgs e) => Close();

    private void OnAboutClick(object sender, RoutedEventArgs e) =>
        MessageBox.Show(
            this,
            $"{AppInfo.Name} v{AppInfo.Version}\n\n作者：{AppInfo.Author}\n项目主页：{AppInfo.Url}\n\n" +
            "C# / WPF 版本（.NET 10）。",
            "关于", MessageBoxButton.OK, MessageBoxImage.Information);

    // ---------- 状态 ----------

    private void SyncMenuState()
    {
        WrapMenu.IsChecked = _config.WrapEnabled;

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

    protected override void OnClosed(EventArgs e)
    {
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
