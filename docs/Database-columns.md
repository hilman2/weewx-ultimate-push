# Database columns

A reading only survives the archive interval if the table has a column for it. Without
one it appears in reports as a current value and is gone at the next archive interval.

WeeWX's standard schema has 113 columns. A well equipped Ecowitt or Ambient station can
fill four times that.

## What the standard schema covers

| Series | Channels |
|---|---|
| `extraTemp`, `extraHumid` | 1..8 |
| `batteryStatus`, `signal` | 1..8 |
| `soilTemp`, `soilMoist` | 1..4 |
| `leafTemp`, `leafWet` | 1..2 |

Everything else has to be added: `soilTemp5` and above, `soilMoist5` and above,
`leafWet3` and above, and approximately twenty-five families that do not exist there at
all, among them `air_ch`, `depth_ch`, `soilEC`, `pm25_` and `leak_`.

## Add only what arrives

```
python -m user.ultimatepush --port 8001 --config /etc/weewx/weewx.conf
```

One upload, and the command prints the statements for exactly the columns your station
needs:

```
20 readings have nowhere to live. They will show up in reports as current
conditions and be gone at the next archive interval. To keep them:

  weectl database add-column soilTemp2 --type REAL --config=/etc/weewx/weewx.conf -y
  weectl database add-column lightning_num --type INTEGER --config=/etc/weewx/weewx.conf -y
  weectl database add-column vpd --type REAL --config=/etc/weewx/weewx.conf -y
  ...

Adding a column changes the table definition and not its rows.
```

Twenty columns for a station with a lightning sensor, two soil probes and a WH52,
rather than four hundred.

## Before running them

The [web interface](Web-interface.md) has a button in each row that runs the same
`ALTER TABLE`. Everything below is the same operation from a terminal.

Back up the database first. Adding a column is not dangerous in itself: on SQLite it
changes the table definition and leaves the rows alone, measured at 7.6 ms on a table
of 300,000 records, with the file the same size afterwards. Removing a column again
means rebuilding the table around it, and a mistyped name is easier to type than to
undo.

```
sudo systemctl stop weewx
cp /var/lib/weewx/weewx.sdb /var/lib/weewx/weewx.sdb.backup
```

Then run the commands and start WeeWX again.

## Column types

`INTEGER` for counted values, `REAL` for measured ones. The tool selects by unit group:
`group_count`, `group_time`, `group_boolean` and `group_data` become `INTEGER`, and
everything else `REAL`.

## Columns that already hold data

This matters before changing anything about a running station, and the driver checks it
in two places.

When a station is set up in the web interface, the archive table is read and the columns
that station would write are checked against it. Anything that already holds readings is
reported, with the number of rows and the date of the most recent one, and the station
is not set up until you confirm. Where the choice can be avoided it is: a channel whose
`extraTempN` and `extraHumidN` already hold readings is skipped when a channel is
assigned automatically. See [Stations](Stations.md).

The diagnostic command reports the same information:

```
12 of these fields already hold readings:

  soilTemp1                     104832 values, last 2026-08-25
  outTemp                       104832 values, last 2026-08-25

If those came from the same sensor, there is nothing to do. If they came
from a different one, this driver is about to write a second series into
the same column, and afterwards the two cannot be told apart.
```

The check is one pass over the archive table, so it is made when the interface is first
opened rather than on every page load.

## Moving a series to another column

```
sudo systemctl stop weewx
weectl database rename-column soilTemp1 extraTemp9 -y
sudo systemctl start weewx
```

Then adjust `field_map_extensions` to match. Renaming keeps the history; mapping the
field elsewhere without renaming starts a second series.

## Starting with a larger schema

For a new installation, a schema that has the extra columns from the outset is easier
than adding them later. See the WeeWX customization guide, *The database*, for how to
point `[DataBindings]` at a schema of your own.
