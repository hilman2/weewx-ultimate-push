# Sensor reference

Every raw field the Ecowitt catalog knows, grouped by the sensor that sends it.
The other five protocols have catalogs of their own; see [Protocols](Protocols.md).

Generated from the catalog by `tools/build_reference.py`. Do not edit by hand.

- **Raw field** is what the console posts.
- **WeeWX field** is where the reading is stored.
- **Waits** means the field is not written until it is named in
  `field_map_extensions`, because where it belongs is not something the hardware
  says. See [Field map](Field-map.md).

Channel counts are Ecowitt's own, from the compatibility table for its consoles and
gateways. A console older than the sensor may support fewer.


## Multi-channel sensors

### LDS01

Up to 4 channels.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `air_ch1` | `air_ch1` | group_lengthmm |  |
| `air_ch2` | `air_ch2` | group_lengthmm |  |
| `air_ch3` | `air_ch3` | group_lengthmm |  |
| `air_ch4` | `air_ch4` | group_lengthmm |  |
| `depth_ch1` | `depth_ch1` | group_lengthmm |  |
| `depth_ch2` | `depth_ch2` | group_lengthmm |  |
| `depth_ch3` | `depth_ch3` | group_lengthmm |  |
| `depth_ch4` | `depth_ch4` | group_lengthmm |  |
| ... | ... | | |
| `wh54sig3` | `wh54_ch3_sig` | group_count |  |
| `wh54sig4` | `wh54_ch4_sig` | group_count |  |

### WH31

Up to 8 channels. WH31 multi-channel temperature and humidity. Placement is the user's.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `batt1` | `batteryStatus1` |  |  |
| `batt2` | `batteryStatus2` |  |  |
| `batt3` | `batteryStatus3` |  |  |
| `batt4` | `batteryStatus4` |  |  |
| `batt5` | `batteryStatus5` |  |  |
| `batt6` | `batteryStatus6` |  |  |
| `batt7` | `batteryStatus7` |  |  |
| `batt8` | `batteryStatus8` |  |  |
| ... | ... | | |
| `wh31sig7` | `wh31_ch7_sig` | group_count |  |
| `wh31sig8` | `wh31_ch8_sig` | group_count |  |

### WH41

Up to 4 channels.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `pm25_avg_24h_ch1` | `pm25_avg_24h_ch1` | group_concentration |  |
| `pm25_avg_24h_ch2` | `pm25_avg_24h_ch2` | group_concentration |  |
| `pm25_avg_24h_ch3` | `pm25_avg_24h_ch3` | group_concentration |  |
| `pm25_avg_24h_ch4` | `pm25_avg_24h_ch4` | group_concentration |  |
| `pm25_ch1` | `pm25_1` | group_concentration |  |
| `pm25_ch2` | `pm25_2` | group_concentration |  |
| `pm25_ch3` | `pm25_3` | group_concentration |  |
| `pm25_ch4` | `pm25_4` | group_concentration |  |
| `pm25batt1` | `pm25_Batt1` | group_count |  |
| `pm25batt2` | `pm25_Batt2` | group_count |  |
| `pm25batt3` | `pm25_Batt3` | group_count |  |
| `pm25batt4` | `pm25_Batt4` | group_count |  |
| `wh41rssi1` | `wh41_ch1_rssi` | group_dbm |  |
| `wh41rssi2` | `wh41_ch2_rssi` | group_dbm |  |
| `wh41rssi3` | `wh41_ch3_rssi` | group_dbm |  |
| `wh41rssi4` | `wh41_ch4_rssi` | group_dbm |  |
| `wh41sig1` | `wh41_ch1_sig` | group_count |  |
| `wh41sig2` | `wh41_ch2_sig` | group_count |  |
| `wh41sig3` | `wh41_ch3_sig` | group_count |  |
| `wh41sig4` | `wh41_ch4_sig` | group_count |  |

### WH51

Up to 16 channels.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `soilad1` | `soilad1` | group_count |  |
| `soilad10` | `soilad10` | group_count |  |
| `soilad11` | `soilad11` | group_count |  |
| `soilad12` | `soilad12` | group_count |  |
| `soilad13` | `soilad13` | group_count |  |
| `soilad14` | `soilad14` | group_count |  |
| `soilad15` | `soilad15` | group_count |  |
| `soilad16` | `soilad16` | group_count |  |
| ... | ... | | |
| `wh51sig8` | `wh51_ch8_sig` | group_count |  |
| `wh51sig9` | `wh51_ch9_sig` | group_count |  |

### WH52

Up to 16 channels.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `soil_ec1` | `soilEC1` | group_usiecm |  |
| `soil_ec10` | `soilEC10` | group_usiecm |  |
| `soil_ec11` | `soilEC11` | group_usiecm |  |
| `soil_ec12` | `soilEC12` | group_usiecm |  |
| `soil_ec13` | `soilEC13` | group_usiecm |  |
| `soil_ec14` | `soilEC14` | group_usiecm |  |
| `soil_ec15` | `soilEC15` | group_usiecm |  |
| `soil_ec16` | `soilEC16` | group_usiecm |  |
| ... | ... | | |
| `soil_ec_temp8` | `soilTemp8` | group_temperature | yes |
| `soil_ec_temp9` | `soilTemp9` | group_temperature | yes |

### WH55

Up to 4 channels.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `leak_ch1` | `leak_1` | group_count |  |
| `leak_ch2` | `leak_2` | group_count |  |
| `leak_ch3` | `leak_3` | group_count |  |
| `leak_ch4` | `leak_4` | group_count |  |
| `leakbatt1` | `leak_Batt1` | group_count |  |
| `leakbatt2` | `leak_Batt2` | group_count |  |
| `leakbatt3` | `leak_Batt3` | group_count |  |
| `leakbatt4` | `leak_Batt4` | group_count |  |
| `wh55rssi1` | `wh55_ch1_rssi` | group_dbm |  |
| `wh55rssi2` | `wh55_ch2_rssi` | group_dbm |  |
| `wh55rssi3` | `wh55_ch3_rssi` | group_dbm |  |
| `wh55rssi4` | `wh55_ch4_rssi` | group_dbm |  |
| `wh55sig1` | `wh55_ch1_sig` | group_count |  |
| `wh55sig2` | `wh55_ch2_sig` | group_count |  |
| `wh55sig3` | `wh55_ch3_sig` | group_count |  |
| `wh55sig4` | `wh55_ch4_sig` | group_count |  |

### WN34

Up to 8 channels. WN34 multi-channel temperature. Sold with a spike, with a PVC lead, and with a silicone lead for a pool. All of them report as tf_chN, so the channel is theirs and the placement is yours. They go to extraTemp9 and up, which is where the Ecowitt gateway driver puts them.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `tf_batt1` | `wn34_ch1_batt` | group_volt | yes |
| `tf_batt10` | `wn34_ch10_batt` | group_volt | yes |
| `tf_batt11` | `wn34_ch11_batt` | group_volt | yes |
| `tf_batt12` | `wn34_ch12_batt` | group_volt | yes |
| `tf_batt13` | `wn34_ch13_batt` | group_volt | yes |
| `tf_batt14` | `wn34_ch14_batt` | group_volt | yes |
| `tf_batt15` | `wn34_ch15_batt` | group_volt | yes |
| `tf_batt16` | `wn34_ch16_batt` | group_volt | yes |
| ... | ... | | |
| `wh34sig8` | `wn34_ch8_sig` | group_count |  |
| `wh34sig9` | `wn34_ch9_sig` | group_count |  |

### WN35

Up to 8 channels. WN35 leaf wetness. Placement is the user's.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `leaf_batt1` | `leafWetBatt1` | group_volt |  |
| `leaf_batt2` | `leafWetBatt2` | group_volt |  |
| `leaf_batt3` | `leafWetBatt3` | group_volt |  |
| `leaf_batt4` | `leafWetBatt4` | group_volt |  |
| `leaf_batt5` | `leafWetBatt5` | group_volt |  |
| `leaf_batt6` | `leafWetBatt6` | group_volt |  |
| `leaf_batt7` | `leafWetBatt7` | group_volt |  |
| `leaf_batt8` | `leafWetBatt8` | group_volt |  |
| ... | ... | | |
| `wh35sig7` | `wn35_ch7_sig` | group_count |  |
| `wh35sig8` | `wn35_ch8_sig` | group_count |  |

## Everything else

Sensors with a single instance, and the readings a station sends regardless of what is attached to it.

| Raw field | WeeWX field | Unit group | Waits |
|---|---|---|---|
| `baromabsin` | `pressure` |  |  |
| `baromrelin` | `barometer` |  |  |
| `bgt` | `bgt` | group_temperature |  |
| `bgtbatt` | `bgtbatt` | group_volt |  |
| `charge` | `charge_stat` | group_count |  |
| `co2` | `co2` | group_fraction |  |
| `co2_24h` | `co2_24h` | group_fraction |  |
| `co2_batt` | `co2_Batt` | group_count |  |
| ... | ... | | |
| `ws90cap_volt` | `ws90cap_volt` | group_volt |  |
| `yrain_piezo` | `yrain_piezo` | group_rain |  |
