using System.Windows;
using System.Windows.Controls;

namespace OhmyPort.App.Views;

/// <summary>下拉选择对话框（日志保留策略 / 字体等）。</summary>
public class ComboSelectDialog : Window
{
    private readonly ComboBox _combo;

    public ComboSelectDialog(string title, string label,
                             IReadOnlyList<(string Label, string Key)> options,
                             string currentKey, string? tip = null)
    {
        Title = title;
        Width = 400;
        Height = tip is null ? 170 : 210;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        ThemeService.AttachWindow(this);

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        if (tip is not null)
        {
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        }
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var labelText = new TextBlock { Text = label, Margin = new Thickness(0, 0, 0, 8) };
        grid.Children.Add(labelText);

        _combo = new ComboBox { MinHeight = 28 };
        foreach (var (lbl, key) in options)
        {
            _combo.Items.Add(new ComboItem(lbl, key));
        }
        _combo.DisplayMemberPath = nameof(ComboItem.Label);
        var idx = options.Select((o, i) => (o.Key, i)).FirstOrDefault(x => x.Key == currentKey).i;
        _combo.SelectedIndex = idx >= 0 ? idx : 0;
        Grid.SetRow(_combo, 1);
        grid.Children.Add(_combo);

        var nextRow = 2;
        if (tip is not null)
        {
            var tipText = new TextBlock
            {
                Text = tip,
                TextWrapping = TextWrapping.Wrap,
                Foreground = (System.Windows.Media.Brush)Application.Current.Resources["Brush.Muted"],
                Margin = new Thickness(0, 8, 0, 0),
            };
            Grid.SetRow(tipText, 2);
            grid.Children.Add(tipText);
            nextRow = 3;
        }

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 16, 0, 0),
        };
        var ok = new Button { Content = "确定", Tag = "accent", Width = 80, Margin = new Thickness(0, 0, 8, 0) };
        ok.Click += (_, _) => DialogResult = true;
        var cancel = new Button { Content = "取消", Width = 80 };
        cancel.Click += (_, _) => DialogResult = false;
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        Grid.SetRow(buttons, nextRow);
        grid.Children.Add(buttons);

        Content = grid;
    }

    public string SelectedKey => (_combo.SelectedItem as ComboItem)?.Key ?? "";

    private sealed record ComboItem(string Label, string Key);
}
