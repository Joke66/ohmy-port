using System.Windows;
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
        if (!All.Contains(key))
        {
            key = Auto;
        }

        ThemeKey = key;
        Resolved = key == Auto ? (IsSystemDark() ? Black : Day) : key;
        ApplyDictionary(Resolved);
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
            return;
        }

        dicts[0] = new ResourceDictionary { Source = new Uri(source, UriKind.Relative) };
    }

    /// <summary>从当前资源字典读取画刷（日志着色用）。</summary>
    public static Brush GetBrush(string key) =>
        (Brush)Application.Current.Resources[key];
}
