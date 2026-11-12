namespace OhmyPort.Core;

/// <summary>
/// 可写数据目录解析（对应 Python 版 common._exe_dir / _data_dir）：
/// 优先 exe 同级目录，不可写则落到 %APPDATA%\OhmyPort。
/// </summary>
public static class AppPaths
{
    private static readonly Lazy<string> LazyDataDir = new(ResolveDataDir);

    public static string ExeDir => AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);

    public static string DataDir => LazyDataDir.Value;

    public static string ConfigPath => Path.Combine(DataDir, "serial_tool_config.json");

    public static string DefaultLogDir => Path.Combine(DataDir, "Logs");

    public static string DefaultBgDir => Path.Combine(DataDir, "background");

    private static string ResolveDataDir()
    {
        var probe = Path.Combine(ExeDir, ".ohmyport_probe");
        try
        {
            File.WriteAllBytes(probe, []);
            File.Delete(probe);
            return ExeDir;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            var appData = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "OhmyPort");
            try
            {
                Directory.CreateDirectory(appData);
                return appData;
            }
            catch (Exception inner) when (inner is IOException or UnauthorizedAccessException)
            {
                return ExeDir;
            }
        }
    }
}
