using System.Windows;
using System.Windows.Controls;

namespace OhmyPort.App.Views;

/// <summary>数字输入对话框（日志分片大小等）。</summary>
public class NumberInputDialog : Window
{
    private readonly TextBox _input;

    public NumberInputDialog(string title, string prompt, int initial, int min, int max)
    {
        Title = title;
        Width = 380;
        Height = 180;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var label = new TextBlock { Text = prompt, Margin = new Thickness(0, 0, 0, 8) };
        Grid.SetRow(label, 0);
        grid.Children.Add(label);

        _input = new TextBox
        {
            Text = initial.ToString(),
            VerticalContentAlignment = VerticalAlignment.Center,
            MinHeight = 28,
        };
        Grid.SetRow(_input, 1);
        grid.Children.Add(_input);

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 16, 0, 0),
        };
        var ok = new Button { Content = "确定", Tag = "accent", Width = 80, Margin = new Thickness(0, 0, 8, 0) };
        ok.Click += (_, _) => OnOk(min, max);
        var cancel = new Button { Content = "取消", Width = 80 };
        cancel.Click += (_, _) => DialogResult = false;
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        Grid.SetRow(buttons, 2);
        grid.Children.Add(buttons);

        Content = grid;
        Loaded += (_, _) => { _input.Focus(); _input.SelectAll(); };
    }

    public int Value { get; private set; }

    private void OnOk(int min, int max)
    {
        if (!int.TryParse(_input.Text.Trim(), out var value))
        {
            MessageBox.Show(this, "请输入有效数字。", "输入无效", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        Value = Math.Clamp(value, min, max);
        DialogResult = true;
    }
}
