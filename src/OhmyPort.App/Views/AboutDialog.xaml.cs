using System.Diagnostics;
using System.Windows;
using System.Windows.Navigation;
using OhmyPort.Core;

namespace OhmyPort.App.Views;

/// <summary>
/// 关于对话框：应用标识 + 开源（GPL）声明 + 作者/技术栈 + 可点击链接 + 无担保与免责。
/// </summary>
public partial class AboutDialog : Window
{
    public AboutDialog()
    {
        InitializeComponent();
        DataContext = new AboutInfo();
    }

    private void OnCloseClick(object sender, RoutedEventArgs e) => Close();

    private void OnViewLicenseClick(object sender, RoutedEventArgs e)
    {
        var viewer = new LicenseViewer { Owner = this };
        viewer.ShowDialog();
    }

    private void OnOpenUrl(object sender, RequestNavigateEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
        }
        catch
        {
            // 打不开就忽略
        }

        e.Handled = true;
    }

    /// <summary>绑定用数据对象。</summary>
    private sealed class AboutInfo
    {
        public string VersionText => $"{AppInfo.Name} v{AppInfo.Version}";
        public string Author => AppInfo.Author;
        public string Url => AppInfo.Url;
    }
}
