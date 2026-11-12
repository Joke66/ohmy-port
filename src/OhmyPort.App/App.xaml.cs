using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Threading;

namespace OhmyPort.App;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        // 压测入口：不加载主界面，直接灌数据测性能
        if (e.Args.Contains("--stress", StringComparer.OrdinalIgnoreCase))
        {
            StressTest.Run();
            return;
        }

        // GBK 等代码页编码需要显式注册（.NET Core 起默认不含）
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnDomainUnhandledException;

        base.OnStartup(e);
    }

    private static void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        WriteError(e.Exception);
        MessageBox.Show($"程序遇到未处理的错误：\n{e.Exception.Message}\n\n详情已写入 error.log。",
                        "OhmyPort", MessageBoxButton.OK, MessageBoxImage.Error);
        e.Handled = true;
    }

    private static void OnDomainUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
        {
            WriteError(ex);
        }
    }

    private static void WriteError(Exception ex)
    {
        try
        {
            File.AppendAllText(
                Path.Combine(AppContext.BaseDirectory, "error.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {ex}\r\n");
        }
        catch (IOException)
        {
            // 日志写不进去就算了，不能因为记日志再崩一次
        }
    }
}
