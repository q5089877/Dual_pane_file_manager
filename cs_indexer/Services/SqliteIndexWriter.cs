using System;
using System.Collections.Generic;
using Microsoft.Data.Sqlite;
using DFE.Indexer.Models;

namespace DFE.Indexer.Services;

public sealed class SqliteIndexWriter : IDisposable
{
    private readonly SqliteConnection _connection;
    private SqliteTransaction? _transaction;

    // In-memory folder cache: avoids repeated SELECT id FROM folders per file
    private readonly Dictionary<string, long> _folderCache = new(StringComparer.OrdinalIgnoreCase);

    // Pre-compiled reusable commands (allocated once, not per file)
    private readonly SqliteCommand _insertFolderCmd;
    private readonly SqliteCommand _getFolderIdCmd;
    private readonly SqliteCommand _upsertFileCmd;
    private readonly SqliteCommand _upsertFingerprintCmd;

    public SqliteIndexWriter(string dbPath)
    {
        _connection = new SqliteConnection($"Data Source={dbPath}");
        _connection.Open();

        _insertFolderCmd = _connection.CreateCommand();
        _insertFolderCmd.CommandText = "INSERT OR IGNORE INTO folders(path) VALUES (@path)";
        _insertFolderCmd.Parameters.Add("@path", SqliteType.Text);

        _getFolderIdCmd = _connection.CreateCommand();
        _getFolderIdCmd.CommandText = "SELECT id FROM folders WHERE path = @path";
        _getFolderIdCmd.Parameters.Add("@path", SqliteType.Text);

        _upsertFileCmd = _connection.CreateCommand();
        _upsertFileCmd.CommandText = @"
            INSERT OR REPLACE INTO files_index(folder_id, name, mtime, size)
            VALUES (@folder_id, @name, @mtime, @size)";
        _upsertFileCmd.Parameters.Add("@folder_id", SqliteType.Integer);
        _upsertFileCmd.Parameters.Add("@name", SqliteType.Text);
        _upsertFileCmd.Parameters.Add("@mtime", SqliteType.Real);
        _upsertFileCmd.Parameters.Add("@size", SqliteType.Integer);

        _upsertFingerprintCmd = _connection.CreateCommand();
        _upsertFingerprintCmd.CommandText = @"
            INSERT OR REPLACE INTO folder_fingerprints(folder_id, mtime)
            VALUES (@folder_id, @folder_mtime)";
        _upsertFingerprintCmd.Parameters.Add("@folder_id", SqliteType.Integer);
        _upsertFingerprintCmd.Parameters.Add("@folder_mtime", SqliteType.Real);
    }

    public void InitializePragmas()
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA cache_size=-10000;
            PRAGMA busy_timeout=5000;";
        cmd.ExecuteNonQuery();
    }

    public void BeginTransaction()
    {
        _transaction = _connection.BeginTransaction();
        _insertFolderCmd.Transaction = _transaction;
        _getFolderIdCmd.Transaction = _transaction;
        _upsertFileCmd.Transaction = _transaction;
        _upsertFingerprintCmd.Transaction = _transaction;
    }

    public void CommitTransaction()
    {
        _transaction?.Commit();
        _transaction?.Dispose();
        _transaction = null;
    }

    public void UpsertFile(FileRecord record)
    {
        long folderId = GetOrInsertFolderId(record.FolderPath);

        _upsertFileCmd.Parameters["@folder_id"].Value = folderId;
        _upsertFileCmd.Parameters["@name"].Value = record.Name;
        _upsertFileCmd.Parameters["@mtime"].Value = record.Mtime;
        _upsertFileCmd.Parameters["@size"].Value = record.Size;
        _upsertFileCmd.ExecuteNonQuery();

        // Update folder fingerprint using the folder's own mtime (approximated from file mtime)
        _upsertFingerprintCmd.Parameters["@folder_id"].Value = folderId;
        _upsertFingerprintCmd.Parameters["@folder_mtime"].Value = record.Mtime;
        _upsertFingerprintCmd.ExecuteNonQuery();
    }

    public void UpdateScanMetadata(string rootPath, string status, int totalFiles)
    {
        using var cmd = _connection.CreateCommand();
        double unixNow = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        cmd.CommandText = @"
            INSERT OR REPLACE INTO scan_metadata(root_path, status, last_finished, total_files)
            VALUES (@root, @status, @now, @total)";
        cmd.Parameters.AddWithValue("@root", rootPath);
        cmd.Parameters.AddWithValue("@status", status);
        cmd.Parameters.AddWithValue("@now", unixNow);
        cmd.Parameters.AddWithValue("@total", totalFiles);
        if (_transaction is not null) cmd.Transaction = _transaction;
        cmd.ExecuteNonQuery();
    }

    /// <summary>Remove a single file from the index. Auto-wrapped in its own transaction.</summary>
    public void DeleteFile(string folderPath, string fileName)
    {
        long? folderId = GetFolderIdOrNull(folderPath);
        if (folderId is null) return;

        using var tx = _connection.BeginTransaction();
        using var cmd = _connection.CreateCommand();
        cmd.Transaction = tx;
        cmd.CommandText = "DELETE FROM files_index WHERE folder_id = @fid AND name = @name";
        cmd.Parameters.AddWithValue("@fid", folderId.Value);
        cmd.Parameters.AddWithValue("@name", fileName);
        cmd.ExecuteNonQuery();
        tx.Commit();
    }

    /// <summary>Rename a file in the index. Auto-wrapped in its own transaction.</summary>
    public void RenameFile(string folderPath, string oldName, string newName)
    {
        long? folderId = GetFolderIdOrNull(folderPath);
        if (folderId is null) return;

        using var tx = _connection.BeginTransaction();
        using var cmd = _connection.CreateCommand();
        cmd.Transaction = tx;
        cmd.CommandText = "UPDATE files_index SET name = @newName WHERE folder_id = @fid AND name = @oldName";
        cmd.Parameters.AddWithValue("@newName", newName);
        cmd.Parameters.AddWithValue("@fid", folderId.Value);
        cmd.Parameters.AddWithValue("@oldName", oldName);
        cmd.ExecuteNonQuery();
        tx.Commit();
    }

    /// <summary>Insert or update a single file. Auto-wrapped in its own transaction.</summary>
    public void UpsertFileSingle(FileRecord record)
    {
        using var tx = _connection.BeginTransaction();
        _insertFolderCmd.Transaction = tx;
        _getFolderIdCmd.Transaction = tx;
        _upsertFileCmd.Transaction = tx;
        _upsertFingerprintCmd.Transaction = tx;

        UpsertFile(record);
        tx.Commit();

        _insertFolderCmd.Transaction = _transaction;
        _getFolderIdCmd.Transaction = _transaction;
        _upsertFileCmd.Transaction = _transaction;
        _upsertFingerprintCmd.Transaction = _transaction;
    }

    private long? GetFolderIdOrNull(string folderPath)
    {
        if (_folderCache.TryGetValue(folderPath, out long cached))
            return cached;

        _getFolderIdCmd.Transaction = null;
        _getFolderIdCmd.Parameters["@path"].Value = folderPath;
        object? result = _getFolderIdCmd.ExecuteScalar();
        _getFolderIdCmd.Transaction = _transaction;
        if (result is null) return null;
        long id = (long)result;
        _folderCache[folderPath] = id;
        return id;
    }

    private long GetOrInsertFolderId(string folderPath)
    {
        // O(1) memory cache hit
        if (_folderCache.TryGetValue(folderPath, out long cachedId))
            return cachedId;

        // Cache miss: insert (idempotent) then fetch id
        _insertFolderCmd.Parameters["@path"].Value = folderPath;
        _insertFolderCmd.ExecuteNonQuery();

        _getFolderIdCmd.Parameters["@path"].Value = folderPath;
        long dbId = (long)(_getFolderIdCmd.ExecuteScalar() ?? throw new InvalidOperationException($"Failed to get id for folder: {folderPath}"));

        _folderCache[folderPath] = dbId;
        return dbId;
    }

    public void Dispose()
    {
        _transaction?.Dispose();
        _insertFolderCmd.Dispose();
        _getFolderIdCmd.Dispose();
        _upsertFileCmd.Dispose();
        _upsertFingerprintCmd.Dispose();
        _connection.Dispose();
    }
}
