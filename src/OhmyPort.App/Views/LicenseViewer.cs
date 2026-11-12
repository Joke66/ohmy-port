using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using OhmyPort.Core;

namespace OhmyPort.App.Views;

/// <summary>
/// 开源许可查看器：读取嵌入的 LICENSE 全文，只读展示。
/// 满足 GPL「告知用户如何查看许可证副本」的要求，且离线可用。
/// </summary>
public class LicenseViewer : Window
{
    public LicenseViewer()
    {
        Title = $"开源许可 — {AppInfo.Name}";
        Width = 560;
        Height = 520;
        MinWidth = 420;
        MinHeight = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.CanResize;
        ShowInTaskbar = false;
        ThemeService.AttachWindow(this);

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var header = new TextBlock
        {
            Text = $"OhmyPort 依据 GNU 通用公共许可证（GPL）第 2 版（或更高版本）发布。完整条款如下：",
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 10),
        };
        Grid.SetRow(header, 0);
        grid.Children.Add(header);

        var viewer = new TextBox
        {
            Text = LoadLicense(),
            IsReadOnly = true,
            TextWrapping = TextWrapping.NoWrap,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            FontFamily = new System.Windows.Media.FontFamily("Consolas"),
            FontSize = 12,
            Padding = new Thickness(8),
            AcceptsReturn = true,
        };
        Grid.SetRow(viewer, 1);
        grid.Children.Add(viewer);

        var close = new Button
        {
            Content = "关闭",
            Width = 80,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 12, 0, 0),
        };
        close.Click += (_, _) => Close();
        Grid.SetRow(close, 2);
        grid.Children.Add(close);

        Content = grid;
    }

    /// <summary>从嵌入资源读 LICENSE 全文；读取失败给兜底文案。</summary>
    private static string LoadLicense()
    {
        try
        {
            var asm = Assembly.GetExecutingAssembly();
            using var stream = asm.GetManifestResourceStream("LICENSE");
            if (stream is null)
            {
                return "未能加载许可证文本。请访问项目主页查看完整 GPL-2.0 条款。";
            }

            using var reader = new StreamReader(stream);
            return reader.ReadToEnd();
        }
        catch (IOException)
        {
            return "未能加载许可证文本。请访问项目主页查看完整 GPL-2.0 条款。";
        }
    }
}
