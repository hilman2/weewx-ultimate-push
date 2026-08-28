# Database columns

A reading only survives the archive interval if the table has a column for it.
Without one it appears in reports as a current value and is gone five minutes later.

WeeWX's standard schema has 113 columns. A well equipped Ecowitt or Ambient station
can fill four times that.

## What the standard schema covers

| Series | Channels |
|---|---|
| `extraTemp`, `extraHumid` | 1..8 |
| `batteryStatus`, `signal` | 1..8 |
| `soilTemp`, `soilMoist` | 1..4 |
| `leafTemp`, `leafWet` | 1..2 |

Everything else needs adding: `soilTemp5` and up, `soilMoist5` and up, `leafWet3` and
up, and about twenty-five families that do not exist there at all, among them
`air_ch`, `depth_ch`, `soilEC`, `pm25_`, `leak_`.

## Add only what arrives

```
python -m user.ultimatepush --port 8001 --config /etc/weewx/weewx.conf
```

One upload, and it prints the commands for exactly the columns your station needs:

```
20 readings have nowhere to live. They will show up in reports as current
conditions and be gone at the next archive interval. To keep them:

  weectl database add-column soilTemp2 --type REAL --config=/etc/weewx/weewx.conf -y
  weectl database add-column lightning_num --type INTEGER --config=/etc/weewx/weewx.conf -y
  weectl database add-column vpd --type REAL --config=/etc/weewx/weewx.conf -y
  ...

Adding a column changes the table definition and not its rows.
```

Twenty columns for a station with a lightning sensor, two soil probes and a WH52. Not
four hundred.

## Before running them

**Or press the button.** The [web interface](Web-interface) has one in the row, and
it runs the same `ALTER TABLE`. Everything below is the same job from a terminal.

**Back up.** Not because adding is dangerous: on SQLite it changes the table
definition and leaves the rows alone, measured at 7.6 ms on a table of 300 000
records, with the file the same size afterwards. Because taking a column away again
means rebuilding the table around it, and a wrong name is easier to type than to
undo. With sqlite:

```
sudo systemctl stop weewx
cp /var/lib/weewx/weewx.sdb /var/lib/weewx/weewx.sdb.backup
```

Then run the commands, then start WeeWX again.

## Types

`INTEGER` for counted things, `REAL` for measured ones. The tool picks by unit group:
`group_count`, `group_time`, `group_boolean` and `group_data` become `INTEGER`,
everything else `REAL`.

## Which columns already hold data

The same command says so, and this is worth reading before changing anything about a
running station:

```
12 of these fields already hold readings:

  soilTemp1                     104832 values, last 2026-08-25
  outTemp                       104832 values, last 2026-08-25

If those came from the same sensor, there is nothing to do. If they came
from a different one, this driver is about to write a second series into
the same column, and afterwards the two cannot be told apart.
```

## Moving a series to another column

```
sudo systemctl stop weewx
weectl database rename-column soilTemp1 extraTemp9 -y
sudo systemctl start weewx
```

Then adjust `field_map_extensions` to match. Renaming keeps the history; mapping the
field elsewhere without renaming starts a second one.

## Starting with a bigger schema

For a new installation, a schema that has the extra columns from the outset is easier
than adding them later. See the WeeWX customization guide, *The database*, for how to
point `[DataBindings]` at a schema of your own.
