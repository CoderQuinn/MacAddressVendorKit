import XCTest
@testable import MacAddressVendorKit

final class MacAddressVendorDatabaseTests: XCTestCase {
    func testBundledDatabaseResolvesMALAssignment() throws {
        let database = try MacAddressVendorDatabase.bundled()
        let result = try database.lookup("F0:EE:7A:00:00:01")

        XCTAssertEqual(result?.organization, "Apple, Inc.")
        XCTAssertEqual(result?.registry, .maL)
        XCTAssertEqual(result?.prefixBits, 24)
    }

    func testLongestPrefixWinsForMAMAndMAS() throws {
        let database = try MacAddressVendorDatabase.bundled()

        let medium = try database.lookup("C8:5C:E2:70:00:01")
        XCTAssertEqual(medium?.registry, .maM)
        XCTAssertEqual(medium?.prefix, "C85CE27")

        let small = try database.lookup("8C:1F:64:AF:A0:01")
        XCTAssertEqual(small?.registry, .maS)
        XCTAssertEqual(small?.prefix, "8C1F64AFA")
    }

    func testHistoricalIABAssignmentIsIncluded() throws {
        let result = try MacAddressVendorDatabase.bundled().lookup("40:D8:55:0D:70:01")

        XCTAssertEqual(result?.registry, .iab)
        XCTAssertEqual(result?.organization, "Avant Technologies")
    }

    func testLocallyAdministeredAndMalformedAddressesDoNotProduceVendorByDefault() throws {
        let database = try MacAddressVendorDatabase.bundled()

        XCTAssertNil(try database.lookup("F2:EE:7A:00:00:01"))
        XCTAssertNil(try database.lookup("invalid"))
        XCTAssertEqual(
            MacAddressVendorDatabase.normalized("f0ee.7a00.0001"),
            "F0EE7A000001"
        )
    }

    func testBundledDatabaseIntegrityAndMetadata() throws {
        let database = try MacAddressVendorDatabase.bundled()

        XCTAssertTrue(try database.integrityCheck())
        XCTAssertEqual(try database.metadata.schemaVersion, 1)
        XCTAssertGreaterThan(try database.metadata.entryCount, 50_000)
    }
}
