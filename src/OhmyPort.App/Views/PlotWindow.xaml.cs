using System.Windows;
using System.Windows.Threading;
using OhmyPort.Core;
using OhmyPort.Core.Models;
using OhmyPort.App.Controls;

namespace OhmyPort.App.Views;

/// <summary>
/// 实时曲线窗口：定时重绘 <see cref="PlotHub"/> 里的采样。
/// 数据属于会话（会话存活期间不清空），窗口关掉再开会接上原有数据。
/// </summary>
public partial class PlotWindow : Window
{
    private readonly PlotHub _hub;
    private readonly Func<List<PlotRuleConfig>> _getRules;
    private readonly Action<List<PlotRuleConfig>> _setRules;
    private readonly DispatcherTimer _timer;

    /// <summary>本窗口对应的会话（同一时刻只给一个会话画图）。</summary>
    public object? OwnerSession { get; init; }

    public PlotWindow(PlotHub hub, string title, int capacity,
                      Func<List<PlotRuleConfig>> getRules,
                      Action<List<PlotRuleConfig>> setRules)
    {
        InitializeComponent();
        _hub = hub;
        _getRules = getRules;
        _setRules = setRules;

        Title = $"实时曲线 — {title}";
        Canvas.Hub = hub;

        PopulatePoints(capacity);
        PointsCombo.SelectionChanged += (_, _) =>
        {
            if (PointsCombo.SelectedItem is Option opt && opt.Value is int points)
            {
                _hub.SetCapacity(points);
                Canvas.InvalidateVisual();
            }
        };

        RulesButton.Click += (_, _) => EditRules();
        ClearButton.Click += (_, _) =>
        {
            _hub.Clear();
            Canvas.InvalidateVisual();
        };

        _timer = new DispatcherTimer(DispatcherPriority.Render)
        {
            Interval = TimeSpan.FromMilliseconds(60),
        };
        _timer.Tick += (_, _) =>
        {
            if (PauseCheck.IsChecked == true)
            {
                return;
            }

            UpdateHint();
            Canvas.InvalidateVisual();
        };
        _timer.Start();

        Loaded += (_, _) => Canvas.InvalidateVisual();
    }

    private void PopulatePoints(int capacity)
    {
        PointsCombo.DisplayMemberPath = nameof(Option.Label);
        PointsCombo.SelectedValuePath = nameof(Option.Value);
        PointsCombo.ItemsSource = new[]
        {
            new Option("200", 200), new Option("600", 600),
            new Option("2000", 2000), new Option("10000", 10000),
        };
        PointsCombo.SelectedValue = capacity;
        if (PointsCombo.SelectedIndex < 0)
        {
            PointsCombo.SelectedIndex = 1;
        }
    }

    private void EditRules()
    {
        var dialog = new PlotRuleDialog(_getRules()) { Owner = this };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        _setRules(dialog.Result);
        Canvas.InvalidateVisual();
    }

    private void UpdateHint()
    {
        if (!_hub.Enabled)
        {
            HintText.Text = "未配置提取规则";
            return;
        }

        var count = _hub.Series.Count == 0 ? 0 : _hub.Series[0].Count;
        HintText.Text = $"{_hub.Series.Count} 条曲线 · {count}/{_hub.Capacity} 点";
    }

    protected override void OnClosed(EventArgs e)
    {
        _timer.Stop();
        base.OnClosed(e);
    }
}
