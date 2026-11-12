using System.Windows;
using System.Windows.Controls;

namespace OhmyPort.App.Views;

/// <summary>关闭确认对话框：最小化到托盘 / 直接退出，可勾选「不再提示」。</summary>
public class CloseConfirmDialog : Window
{
    private readonly CheckBox _noAsk = new();

    public CloseConfirmDialog()
    {
        Title = "关闭";
        Width = 360;
        Height = 190;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        ThemeService.AttachWindow(this);

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var text = new TextBlock { Text = "关闭时是否最小化到托盘？", Margin = new Thickness(0, 0, 0, 12) };
        grid.Children.Add(text);

        _noAsk.Content = "不再提示";
        _noAsk.Margin = new Thickness(0, 0, 0, 8);
        Grid.SetRow(_noAsk, 1);
        grid.Children.Add(_noAsk);

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Bottom,
        };
        var tray = new Button { Content = "最小化到托盘", Tag = "accent", MinWidth = 110, Margin = new Thickness(0, 0, 8, 0) };
        tray.Click += (_, _) => { ToTray = true; DialogResult = true; };
        var exit = new Button { Content = "直接退出", MinWidth = 90 };
        exit.Click += (_, _) => { ToTray = false; DialogResult = true; };
        buttons.Children.Add(tray);
        buttons.Children.Add(exit);
        Grid.SetRow(buttons, 2);
        grid.Children.Add(buttons);

        Content = grid;
    }

    public bool ToTray { get; private set; }

    public bool DoNotAskAgain => _noAsk.IsChecked == true;
}
