using System.IO;
using System.Windows;
using System.Windows.Controls;

namespace OhmyPort.App.Views;

/// <summary>背景皮肤对话框（对应 Python 版 _open_background_dialog）。</summary>
public class BackgroundDialog : Window
{
    private static readonly string[] ImageExts = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"];

    private readonly ComboBox _imageCombo = new();
    private readonly Slider _blurSlider = new();
    private readonly CheckBox _enableCheck = new();
    private readonly TextBlock _hint = new();
    private string _dir;

    public BackgroundDialog(string bgDir, string bgImage, int bgBlur, bool bgEnabled)
    {
        Title = "背景皮肤";
        Width = 480;
        Height = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        ShowInTaskbar = false;

        _dir = string.IsNullOrEmpty(bgDir) ? OhmyPort.Core.AppPaths.DefaultBgDir : bgDir;
        Directory.CreateDirectory(_dir);

        var grid = new Grid { Margin = new Thickness(16) };
        for (var i = 0; i < 5; i++)
        {
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        }
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        // 目录行：提示 + 选择/打开/刷新
        var dirRow = new Grid { Margin = new Thickness(0, 0, 0, 8) };
        dirRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        dirRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        dirRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        dirRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        _hint.Text = $"背景图存放目录：{_dir}";
        _hint.TextWrapping = TextWrapping.Wrap;
        _hint.Foreground = (System.Windows.Media.Brush)Application.Current.Resources["Brush.Muted"];
        _hint.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(_hint, 0);
        dirRow.Children.Add(_hint);

        var chooseBtn = MakeButton("选择目录...", () => ChooseDir());
        Grid.SetColumn(chooseBtn, 1);
        dirRow.Children.Add(chooseBtn);

        var openBtn = MakeButton("打开目录", () => OpenDir());
        Grid.SetColumn(openBtn, 2);
        dirRow.Children.Add(openBtn);

        var refreshBtn = MakeButton("刷新", () => RefreshImages());
        Grid.SetColumn(refreshBtn, 3);
        dirRow.Children.Add(refreshBtn);

        Grid.SetRow(dirRow, 0);
        grid.Children.Add(dirRow);

        // 图片下拉
        var imgLabel = new TextBlock { Text = "背景图片", Margin = new Thickness(0, 0, 0, 6) };
        Grid.SetRow(imgLabel, 1);
        grid.Children.Add(imgLabel);

        _imageCombo.MinHeight = 28;
        Grid.SetRow(_imageCombo, 2);
        grid.Children.Add(_imageCombo);

        // 模糊强度
        var blurLabel = new TextBlock { Text = "模糊强度", Margin = new Thickness(0, 12, 0, 6) };
        Grid.SetRow(blurLabel, 3);
        grid.Children.Add(blurLabel);

        _blurSlider.Minimum = 0;
        _blurSlider.Maximum = 50;
        _blurSlider.Value = bgBlur;
        Grid.SetRow(_blurSlider, 4);
        grid.Children.Add(_blurSlider);

        _enableCheck.Content = "启用背景";
        _enableCheck.IsChecked = bgEnabled;
        _enableCheck.Margin = new Thickness(0, 10, 0, 0);
        Grid.SetRow(_enableCheck, 5);
        grid.Children.Add(_enableCheck);

        RefreshImages();
        SelectImage(bgImage);

        // 确定/取消
        var buttonsRow = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 16, 0, 0) };
        var ok = new Button { Content = "确定", Tag = "accent", Width = 80, Margin = new Thickness(0, 0, 8, 0) };
        ok.Click += (_, _) =>
        {
            BgDir = _dir;
            BgImage = _imageCombo.SelectedItem as string ?? "";
            BgBlur = (int)_blurSlider.Value;
            BgEnabled = _enableCheck.IsChecked == true;
            DialogResult = true;
        };
        var cancel = new Button { Content = "取消", Width = 80 };
        cancel.Click += (_, _) => DialogResult = false;
        buttonsRow.Children.Add(ok);
        buttonsRow.Children.Add(cancel);
        Grid.SetRow(buttonsRow, 6);
        grid.Children.Add(buttonsRow);
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        Content = grid;
    }

    public string BgDir { get; private set; } = "";
    public string BgImage { get; private set; } = "";
    public int BgBlur { get; private set; }
    public bool BgEnabled { get; private set; }

    private static Button MakeButton(string text, Action onClick)
    {
        var btn = new Button { Content = text, Margin = new Thickness(4, 0, 0, 0) };
        btn.Click += (_, _) => onClick();
        return btn;
    }

    private void ChooseDir()
    {
        using var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "选择背景图目录",
            SelectedPath = _dir,
            UseDescriptionForTitle = true,
        };
        if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK)
        {
            return;
        }

        _dir = dialog.SelectedPath;
        _hint.Text = $"背景图存放目录：{_dir}";
        RefreshImages();
    }

    private void OpenDir()
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("explorer.exe", _dir)
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // 打开失败忽略
        }
    }

    private void RefreshImages()
    {
        var selected = _imageCombo.SelectedItem as string ?? "";
        _imageCombo.Items.Clear();
        _imageCombo.Items.Add("无");

        try
        {
            foreach (var file in Directory.EnumerateFiles(_dir).OrderBy(f => f, StringComparer.OrdinalIgnoreCase))
            {
                if (ImageExts.Contains(Path.GetExtension(file).ToLowerInvariant()))
                {
                    _imageCombo.Items.Add(Path.GetFileName(file));
                }
            }
        }
        catch
        {
            // 目录不可读
        }

        SelectImage(selected);
    }

    private void SelectImage(string? name)
    {
        if (string.IsNullOrEmpty(name))
        {
            _imageCombo.SelectedIndex = 0;
            return;
        }

        for (var i = 0; i < _imageCombo.Items.Count; i++)
        {
            if (string.Equals(_imageCombo.Items[i] as string, name, StringComparison.OrdinalIgnoreCase))
            {
                _imageCombo.SelectedIndex = i;
                return;
            }
        }

        _imageCombo.SelectedIndex = 0;
    }
}
