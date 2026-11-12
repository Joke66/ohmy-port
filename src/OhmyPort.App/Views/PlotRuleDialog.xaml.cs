using System.Collections.ObjectModel;
using System.Windows;
using OhmyPort.Core.Models;

namespace OhmyPort.App.Views;

/// <summary>曲线提取规则编辑对话框：一行一条曲线（名称 + 正则/关键词）。</summary>
public partial class PlotRuleDialog : Window
{
    private readonly ObservableCollection<RuleRow> _rows = [];

    public PlotRuleDialog(IEnumerable<PlotRuleConfig> rules)
    {
        InitializeComponent();
        foreach (var r in rules)
        {
            _rows.Add(new RuleRow(r.Name, r.Pattern));
        }

        RuleList.ItemsSource = _rows;
    }

    public List<PlotRuleConfig> Result { get; private set; } = [];

    private void OnAddRowClick(object sender, RoutedEventArgs e) =>
        _rows.Add(new RuleRow($"曲线{_rows.Count + 1}", ""));

    private void OnDeleteRowClick(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: RuleRow row })
        {
            _rows.Remove(row);
        }
    }

    private void OnOkClick(object sender, RoutedEventArgs e)
    {
        var result = new List<PlotRuleConfig>();
        foreach (var row in _rows)
        {
            var name = row.Name.Trim();
            var pattern = row.Pattern.Trim();
            if (name.Length == 0 && pattern.Length == 0)
            {
                continue;
            }

            if (name.Length == 0 || pattern.Length == 0)
            {
                MessageBox.Show(this, "曲线名称和提取规则都不能为空。", "规则有误",
                                MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            result.Add(new PlotRuleConfig(name, pattern));
        }

        Result = result;
        DialogResult = true;
    }

    private void OnCancelClick(object sender, RoutedEventArgs e) => DialogResult = false;
}

/// <summary>一行规则的编辑态。</summary>
public sealed class RuleRow
{
    public RuleRow(string name, string pattern)
    {
        Name = name;
        Pattern = pattern;
    }

    public string Name { get; set; }

    public string Pattern { get; set; }
}
