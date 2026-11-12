using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using Microsoft.Win32;

namespace OhmyPort.App;

/// <summary>
/// 主题管理：四套主题（auto/black/day/eye）+ 系统深浅跟随。
/// auto 解析为 black（系统深色）或 day（系统浅色）。
/// </summary>
public static class ThemeService
{
    public const string Auto = "auto";
    public const string Black = "black";
    public const string Day = "day";
    public const string Eye = "eye";

    private static readonly string[] All = [Auto, Black, Day, Eye];

    /// <summary>用户选择的主题键（auto 可能）。</summary>
    public static string ThemeKey { get; private set; } = Auto;

    /// <summary>实际生效的主题（black/day/eye，auto 已解析）。</summary>
    public static string Resolved { get; private set; } = Black;

    public static event Action? ThemeChanged;

    /// <summary>应用主题；auto 时按当前系统深浅解析。</summary>
    public static void Apply(string key)
    {
        key = (key ?? "").Trim().ToLowerInvariant();
        if (!All.Contains(key))
        {
            key = Auto;
        }

        ThemeKey = key;
        Resolved = key == Auto ? (IsSystemDark() ? Black : Day) : key;
        ApplyDictionary(Resolved);
        RefreshTitleBars();
        ThemeChanged?.Invoke();
    }

    /// <summary>auto 模式下由轮询器调用：系统深浅变化时刷新。</summary>
    public static void RefreshIfAuto()
    {
        if (ThemeKey != Auto)
        {
            return;
        }

        var resolved = IsSystemDark() ? Black : Day;
        if (resolved != Resolved)
        {
            Resolved = resolved;
            ApplyDictionary(resolved);
            RefreshTitleBars();
            ThemeChanged?.Invoke();
        }
    }

    public static bool IsSystemDark()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            return (int)(key?.GetValue("AppsUseLightTheme") ?? 1) == 0;
        }
        catch
        {
            return false;
        }
    }

    private static void ApplyDictionary(string resolved)
    {
        var source = resolved switch
        {
            Day => "Themes/Light.xaml",
            Eye => "Themes/Eye.xaml",
            _ => "Themes/Dark.xaml",
        };

        var dicts = Application.Current.Resources.MergedDictionaries;
        // 约定：[0] 主题字典，[1] Base.xaml 控件样式
        if (dicts.Count == 0)
        {
            dicts.Add(new ResourceDictionary { Source = new Uri(source, UriKind.Relative) });
            ApplySurfaceBrushes();
            return;
        }

        dicts[0] = new ResourceDictionary { Source = new Uri(source, UriKind.Relative) };
        ApplySurfaceBrushes();
    }

    /// <summary>背景皮肤是否开启（大面积容器半透明）。</summary>
    private static bool _translucentSurfaces;

    /// <summary>
    /// 背景皮肤开启 / 关闭时调用：把大面积容器（日志区、命令页、标签条、状态栏）
    /// 用的 Surface 画刷换成带透明度的版本，让背景图透出来。
    /// </summary>
    public static void SetSurfaceTranslucency(bool enabled)
    {
        _translucentSurfaces = enabled;
        ApplySurfaceBrushes();
    }

    /// <summary>背景皮肤开启时被本地覆盖的“大面积容器”画刷。</summary>
    private static readonly string[] SurfaceKeys = ["Brush.Surface", "Brush.LogSurface", "Brush.MenuBar"];

    private static void ApplySurfaceBrushes()
    {
        var resources = Application.Current?.Resources;
        if (resources is null)
        {
            return;
        }

        if (!_translucentSurfaces)
        {
            // 移除本地覆盖，回落到主题字典里的不透明画刷
            foreach (var key in SurfaceKeys)
            {
                resources.Remove(key);
            }

            return;
        }

        // 和原版一样：背景图是唯一满强度的基底，容器只保留很淡的一层底色。
        // 菜单栏透明度高一些，保证菜单文字始终可读。
        resources["Brush.MenuBar"] = Translucent("Brush.Panel", 0xE6);
        resources["Brush.Surface"] = Translucent("Brush.Panel", 0x38);
        resources["Brush.LogSurface"] = Translucent("Brush.LogBackground", 0x4D);
    }

    /// <summary>取当前主题里的画刷颜色，替换成指定透明度。</summary>
    private static Brush Translucent(string key, byte alpha)
    {
        var brush = Application.Current.TryFindResource(key) as SolidColorBrush;
        var color = brush?.Color ?? Colors.Transparent;
        return new SolidColorBrush(Color.FromArgb(alpha, color.R, color.G, color.B));
    }

    /// <summary>从当前资源字典读取画刷（日志着色用）。</summary>
    public static Brush GetBrush(string key) =>
        (Brush)Application.Current.Resources[key];

    /// <summary>当前生效主题是否为深色（标题栏跟随用）。</summary>
    public static bool IsDark => Resolved == Black;

    /// <summary>
    /// 给窗口补上主题外观：背景 / 前景 / 字体 + 标题栏深浅。
    /// XAML 里声明的窗口用 <c>Style="{StaticResource Theme.Window}"</c>，
    /// 代码里 new 出来的对话框调这里。
    /// </summary>
    public static void AttachWindow(Window window)
    {
        if (window.Style is null && Application.Current?.TryFindResource("Theme.Window") is Style style)
        {
            window.Style = style;
        }

        window.SetResourceReference(Window.BackgroundProperty, "Brush.Window");
        window.SetResourceReference(Window.ForegroundProperty, "Brush.Foreground");

        window.SourceInitialized += (_, _) => ApplyTitleBarTheme(window);
        window.Loaded += (_, _) => ApplyTitleBarTheme(window);
        if (window.IsLoaded)
        {
            ApplyTitleBarTheme(window);
        }
    }

    /// <summary>切换主题后刷新所有已打开窗口的标题栏颜色。</summary>
    public static void RefreshTitleBars()
    {
        if (Application.Current is null)
        {
            return;
        }

        foreach (Window window in Application.Current.Windows)
        {
            ApplyTitleBarTheme(window);
        }
    }

    private static void ApplyTitleBarTheme(Window window)
    {
        var hwnd = new WindowInteropHelper(window).Handle;
        if (hwnd == IntPtr.Zero)
        {
            return;
        }

        // DWMWA_USE_IMMERSIVE_DARK_MODE：20 = Win10 1903+，失败时退回 19（1809）
        var dark = IsDark ? 1 : 0;
        if (DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int)) != 0)
        {
            DwmSetWindowAttribute(hwnd, 19, ref dark, sizeof(int));
        }
    }

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
}
