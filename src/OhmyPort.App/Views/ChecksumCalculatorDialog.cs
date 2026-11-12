using System.Windows;
using System.Windows.Controls;
using OhmyPort.Core;
using OhmyPort.Core.Serial;

namespace OhmyPort.App.Views;

/// <summary>校验计算器：输入 HEX 字节，实时显示 SUM8 / XOR8 / CRC16-Modbus 结果并可复制。</summary>
public class ChecksumCalculatorDialog : Window
{
    private readonly TextBox _input = new();
    private readonly TextBox _sum = new();
    private readonly TextBox _xor = new();
    private readonly TextBox _crc = new();

    public ChecksumCalculatorDialog()
    {
        Title = "校验计算器";
        Width = 440;
        Height = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;
        ThemeService.AttachWindow(this);

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var label = new TextBlock { Text = "HEX 输入（如 01 03 00 00 00 0A）：", Margin = new Thickness(0, 0, 0, 6) };
        Grid.SetRow(label, 0);
        grid.Children.Add(label);

        _input.MinHeight = 28;
        _input.FontFamily = new System.Windows.Media.FontFamily("Consolas");
        _input.TextChanged += (_, _) => Recalc();
        Grid.SetRow(_input, 1);
        grid.Children.Add(_input);

        var results = new StackPanel { Orientation = Orientation.Vertical, Margin = new Thickness(0, 12, 0, 0) };
        results.Children.Add(MakeRow("SUM8（和校验）", _sum));
        results.Children.Add(MakeRow("XOR8（异或校验）", _xor));
        results.Children.Add(MakeRow("CRC16-Modbus", _crc));
        Grid.SetRow(results, 2);
        grid.Children.Add(results);

        var close = new Button
        {
            Content = "关闭",
            Width = 80,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 16, 0, 0),
        };
        close.Click += (_, _) => Close();
        Grid.SetRow(close, 3);
        grid.Children.Add(close);

        Content = grid;
        Loaded += (_, _) => _input.Focus();
    }

    private static Grid MakeRow(string title, TextBox valueBox)
    {
        var g = new Grid { Margin = new Thickness(0, 0, 0, 8) };
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var label = new TextBlock { Text = title, VerticalAlignment = VerticalAlignment.Center };
        Grid.SetColumn(label, 0);
        g.Children.Add(label);

        valueBox.IsReadOnly = true;
        valueBox.MinWidth = 120;
        valueBox.FontFamily = new System.Windows.Media.FontFamily("Consolas");
        valueBox.VerticalContentAlignment = VerticalAlignment.Center;
        Grid.SetColumn(valueBox, 1);
        g.Children.Add(valueBox);

        var copy = new Button { Content = "复制", Margin = new Thickness(8, 0, 0, 0) };
        copy.Click += (_, _) => CopyToClipboard(valueBox.Text);
        Grid.SetColumn(copy, 2);
        g.Children.Add(copy);

        return g;
    }

    private void Recalc()
    {
        var data = SendCodec.ParseHex(_input.Text);
        if (data is null || data.Length == 0)
        {
            _sum.Text = _xor.Text = _crc.Text = "";
            return;
        }

        _sum.Text = ToHex(FrameParser.ChecksumBytes(ChecksumKind.Sum8, data));
        _xor.Text = ToHex(FrameParser.ChecksumBytes(ChecksumKind.Xor8, data));
        _crc.Text = ToHex(FrameParser.ChecksumBytes(ChecksumKind.Crc16Modbus, data));
    }

    private static string ToHex(byte[] data) =>
        string.Join(" ", data.Select(b => b.ToString("X2")));

    private static void CopyToClipboard(string text)
    {
        if (text.Length == 0)
        {
            return;
        }

        try
        {
            Clipboard.SetText(text);
        }
        catch (System.Runtime.InteropServices.COMException)
        {
            // 剪贴板被占用
        }
    }
}
