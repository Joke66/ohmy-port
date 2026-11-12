using System.Text;
using OhmyPort.Core;

namespace OhmyPort.Core.Logging;

/// <summary>
/// 单个会话的记录文件管理 + 日志目录保留清理（对应 Python 版 log_manager.LogManager）。
/// </summary>
public sealed class LogManager
{
    private readonly object _gate = new();
    private FileStream? _stream;
    private string _stem = "serial";
    private string _path = "";

    public string? Error { get; private set; }
    public string Path => _path;

    public bool IsOpen
    {
        get
        {
            lock (_gate)
            {
                return _stream is not null;
            }
        }
    }

    /// <summary>以端口名 stem 打开新记录文件，成功返回路径，失败返回 null。</summary>
    public string? Open(string stem, string logDir)
    {
        lock (_gate)
        {
            CloseCore();
            _stem = SanitizeStem(stem);
            var name = $"{_stem}_{DateTime.Now:yyyyMMdd_HHmmss}.txt";
            var path = System.IO.Path.Combine(logDir, name);
            try
            {
                Directory.CreateDirectory(logDir);
                _stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
                _path = path;
                Error = null;
                return _path;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                _stream = null;
                _path = "";
                Error = ex.Message;
                return null;
            }
        }
    }

    /// <summary>写一行（自动补换行）；异常时记录错误并关闭（磁盘满 / 权限）。</summary>
    public void Write(string line)
    {
        lock (_gate)
        {
            if (_stream is null)
            {
                return;
            }

            try
            {
                var bytes = Encoding.UTF8.GetBytes(line + "\r\n");
                _stream.Write(bytes, 0, bytes.Length);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Error = ex.Message;
                CloseCore();
            }
        }
    }

    /// <summary>刷新并检查大小，超过 shardMb 自动分片。</summary>
    public void Flush(int shardMb, string logDir)
    {
        lock (_gate)
        {
            if (_stream is null)
            {
                return;
            }

            try
            {
                _stream.Flush();
                if (_stream.Length >= (long)shardMb * 1024 * 1024)
                {
                    RotateCore(logDir);
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Error = ex.Message;
                CloseCore();
            }
        }
    }

    public void Rotate(string logDir)
    {
        lock (_gate)
        {
            RotateCore(logDir);
        }
    }

    private void RotateCore(string logDir)
    {
        CloseCore();
        Open(_stem, logDir);
    }

    public void Close()
    {
        lock (_gate)
        {
            CloseCore();
        }
    }

    private void CloseCore()
    {
        try
        {
            _stream?.Dispose();
        }
        catch
        {
            // 关闭失败无所谓
        }

        _stream = null;
        _path = "";
    }

    /// <summary>按保留策略清理旧日志（仅 *.txt）。</summary>
    public static void CleanOldLogs(string logDir, string retentionKey)
    {
        var days = LogRetention.DaysOf(retentionKey);
        if (days <= 0 || !Directory.Exists(logDir))
        {
            return;
        }

        var cutoff = DateTime.Now.AddDays(-days);
        try
        {
            foreach (var file in Directory.EnumerateFiles(logDir, "*.txt"))
            {
                try
                {
                    if (File.GetLastWriteTime(file) < cutoff)
                    {
                        File.Delete(file);
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    // 单个文件删除失败不影响其余文件
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 目录不可读
        }
    }

    /// <summary>端口名 → 安全文件名（对应 re.sub(r"[^0-9A-Za-z_-]", "_", stem)）。</summary>
    private static string SanitizeStem(string? stem)
    {
        var text = new StringBuilder();
        foreach (var ch in stem ?? "")
        {
            var keep = ch is >= '0' and <= '9' or >= 'A' and <= 'Z' or >= 'a' and <= 'z' or '_' or '-';
            text.Append(keep ? ch : '_');
        }

        return text.Length == 0 ? "serial" : text.ToString();
    }
}
