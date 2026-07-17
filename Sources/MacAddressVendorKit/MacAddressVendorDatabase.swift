import Foundation
import SQLite3

private let sqliteTransient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

public enum MacAddressRegistry: String, Codable, Equatable, Sendable {
    case maL = "MA-L"
    case maM = "MA-M"
    case maS = "MA-S"
    case iab = "IAB"
}

public struct MacAddressVendorAssignment: Equatable, Sendable {
    public let prefix: String
    public let prefixBits: Int
    public let registry: MacAddressRegistry
    public let organization: String
}

public struct MacAddressVendorMetadata: Equatable, Sendable {
    public let schemaVersion: Int
    public let generatedAt: String
    public let entryCount: Int
}

public enum MacAddressVendorDatabaseError: Error, Equatable {
    case resourceMissing
    case openFailed
    case queryFailed
    case malformedMetadata
}

public final class MacAddressVendorDatabase: @unchecked Sendable {
    private let connection: OpaquePointer
    private let lock = NSLock()

    public static func bundled() throws -> MacAddressVendorDatabase {
        guard let url = Bundle.module.url(
            forResource: "mac_address_vendors",
            withExtension: "sqlite3"
        ) else {
            throw MacAddressVendorDatabaseError.resourceMissing
        }
        return try MacAddressVendorDatabase(databaseURL: url)
    }

    public init(databaseURL: URL) throws {
        var database: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(databaseURL.path, &database, flags, nil) == SQLITE_OK,
              let database
        else {
            if let database { sqlite3_close(database) }
            throw MacAddressVendorDatabaseError.openFailed
        }
        connection = database
    }

    deinit {
        sqlite3_close(connection)
    }

    public var metadata: MacAddressVendorMetadata {
        get throws {
            lock.lock()
            defer { lock.unlock() }
            guard let schemaVersion = try metadataValueLocked(for: "schema_version"),
                  let generatedAt = try metadataValueLocked(for: "generated_at"),
                  let entryCountRaw = try metadataValueLocked(for: "entry_count"),
                  let version = Int(schemaVersion),
                  let entryCount = Int(entryCountRaw)
            else {
                throw MacAddressVendorDatabaseError.malformedMetadata
            }
            return MacAddressVendorMetadata(
                schemaVersion: version,
                generatedAt: generatedAt,
                entryCount: entryCount
            )
        }
    }

    public func lookup(
        _ macAddress: String,
        includeNonGlobalAddresses: Bool = false
    ) throws -> MacAddressVendorAssignment? {
        let assignments = try lookupAll(
            macAddress,
            includeNonGlobalAddresses: includeNonGlobalAddresses
        )
        return assignments.count == 1 ? assignments[0] : nil
    }

    /// Returns all assignees at the most-specific matching prefix.
    ///
    /// IEEE public listings contain a small number of historical duplicate
    /// prefixes. `lookup` returns nil for those ambiguous prefixes; callers
    /// that need to explain the ambiguity can use this method.
    public func lookupAll(
        _ macAddress: String,
        includeNonGlobalAddresses: Bool = false
    ) throws -> [MacAddressVendorAssignment] {
        guard let normalized = Self.normalized(macAddress) else { return [] }
        guard let firstByte = UInt8(normalized.prefix(2), radix: 16) else { return [] }
        if !includeNonGlobalAddresses,
           (firstByte & 0x01) != 0 || (firstByte & 0x02) != 0
        {
            return []
        }

        lock.lock()
        defer { lock.unlock() }
        for prefixBits in [36, 28, 24] {
            let prefixLength = prefixBits / 4
            let prefix = String(normalized.prefix(prefixLength))
            let assignments = try assignmentsLocked(prefix: prefix, prefixBits: prefixBits)
            if !assignments.isEmpty {
                return assignments
            }
        }
        return []
    }

    public func integrityCheck() throws -> Bool {
        lock.lock()
        defer { lock.unlock() }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(connection, "PRAGMA integrity_check", -1, &statement, nil) == SQLITE_OK,
              let statement
        else {
            throw MacAddressVendorDatabaseError.queryFailed
        }
        defer { sqlite3_finalize(statement) }
        guard sqlite3_step(statement) == SQLITE_ROW,
              let text = sqlite3_column_text(statement, 0)
        else {
            throw MacAddressVendorDatabaseError.queryFailed
        }
        return String(cString: text) == "ok"
    }

    public static func normalized(_ rawValue: String) -> String? {
        let removable = CharacterSet(charactersIn: ":-. ")
            .union(.whitespacesAndNewlines)
        let scalars = rawValue.unicodeScalars.filter { !removable.contains($0) }
        let normalized = String(String.UnicodeScalarView(scalars)).uppercased()
        guard normalized.count == 12 || normalized.count == 16 else { return nil }
        let hexadecimalDigits = CharacterSet(charactersIn: "0123456789ABCDEF")
        guard normalized.unicodeScalars.allSatisfy({ hexadecimalDigits.contains($0) }) else {
            return nil
        }
        return normalized
    }

    private func assignmentsLocked(
        prefix: String,
        prefixBits: Int
    ) throws -> [MacAddressVendorAssignment] {
        let sql = """
        SELECT prefix, prefix_bits, registry, organization
        FROM assignments
        WHERE prefix = ?1 AND prefix_bits = ?2
        ORDER BY registry
        """
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(connection, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else {
            throw MacAddressVendorDatabaseError.queryFailed
        }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, prefix, -1, sqliteTransient)
        sqlite3_bind_int(statement, 2, Int32(prefixBits))
        var assignments: [MacAddressVendorAssignment] = []
        while true {
            let result = sqlite3_step(statement)
            if result == SQLITE_DONE { return assignments }
            guard result == SQLITE_ROW,
                  let prefixText = sqlite3_column_text(statement, 0),
                  let registryText = sqlite3_column_text(statement, 2),
                  let organizationText = sqlite3_column_text(statement, 3),
                  let registry = MacAddressRegistry(rawValue: String(cString: registryText))
            else {
                throw MacAddressVendorDatabaseError.queryFailed
            }
            assignments.append(
                MacAddressVendorAssignment(
                    prefix: String(cString: prefixText),
                    prefixBits: Int(sqlite3_column_int(statement, 1)),
                    registry: registry,
                    organization: String(cString: organizationText)
                )
            )
        }
    }

    private func metadataValueLocked(for key: String) throws -> String? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(
            connection,
            "SELECT value FROM metadata WHERE key = ?1",
            -1,
            &statement,
            nil
        ) == SQLITE_OK,
            let statement
        else {
            throw MacAddressVendorDatabaseError.queryFailed
        }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, key, -1, sqliteTransient)
        let result = sqlite3_step(statement)
        if result == SQLITE_DONE { return nil }
        guard result == SQLITE_ROW, let value = sqlite3_column_text(statement, 0) else {
            throw MacAddressVendorDatabaseError.queryFailed
        }
        return String(cString: value)
    }
}
