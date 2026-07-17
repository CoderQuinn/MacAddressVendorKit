# MacAddressVendorKit

Private Swift Package for offline vendor-clue lookup from IEEE Registration Authority public MA-L, MA-M, MA-S, and historical IAB listings.

The package bundles a generated SQLite database and resolves the most-specific registered prefix first: 36-bit, 28-bit, then 24-bit. Locally administered and multicast addresses return no vendor by default because an IEEE assignee is not a reliable identity signal for those addresses.

```swift
import MacAddressVendorKit

let database = try MacAddressVendorDatabase.bundled()
let assignment = try database.lookup("F0:EE:7A:00:00:01")
```

Runtime lookup is fully offline. The app never contacts IEEE during scanning.

## Authoritative upstream contract

IEEE publishes registry data as CSV downloads rather than a fetchable Git repository. For that reason this repository intentionally has no fake `up` Git remote. `upstream_sources.json` records the official URLs, SHA-256 hashes, row counts, and snapshot date.

```bash
python3 Tools/generate_database.py --input-dir /path/to/ieee-csvs
python3 -m unittest discover Tools/tests
swift test
```

GitHub Actions refreshes from IEEE each week and creates a private `data-YYYY.MM.DD` release.

## Data rights

Code and data rights are separate. See [DATA-NOTICE.md](DATA-NOTICE.md). Keep the repository and its data releases private until IEEE redistribution permission and product governance have been reviewed.
