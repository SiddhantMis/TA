```
Pattern lab: 13556 events in 360 stocks, 2017-08-18 to 2026-10-30, IS/OOS split 2023-08-11, liquid top 200 (point-in-time), cost 0.3%
Baseline (market-adjusted mean 20d return, all liquid stock-days by trend state): uptrend +0.21%  mixed -0.52%  downtrend -0.14%
ex = direction-adjusted return beyond market AND same-trend-state baseline, in %. R = trade outcome with the pattern's own stop/target.

pattern                       per       n   /yr    ex5   ex10   ex20   win%  99% CI of ex20   avgR   Rwin
ascending_triangle (bull)     IS      223  37.3  -0.73  -1.14  -1.68    42%     [-3.4,+0.1]  -0.12    39%
ascending_triangle (bull)     OOS     127  39.4  +0.13  +0.91  +1.72    54%     [-0.6,+4.4]  +0.06    49%
bear_flag (bear)              IS     1514 253.2  -0.23  -0.51  -0.50    51%     [-1.5,+0.5]  -0.26    31%
bear_flag (bear)              OOS     971 301.6  -0.13  -0.30  -0.29    52%     [-1.0,+0.7]  -0.15    33%
bull_flag (bull)              IS     2087 349.0  -0.24  -0.22  -0.29    43%     [-0.9,+0.4]  +0.09    45%
bull_flag (bull)              OOS    1057 328.3  -0.21  -0.03  -0.21    43%     [-1.0,+0.7]  +0.02    43%
descending_triangle (bear)    IS      173  28.9  +0.23  +0.00  +0.41    54%     [-1.6,+2.5]  -0.20    37%
descending_triangle (bear)    OOS     103  32.0  +0.56  +0.75  +0.64    55%     [-0.8,+2.2]  +0.04    43%
double_bottom (bull)          IS      899 150.3  -0.18  -0.19  -0.40    44%     [-1.3,+0.5]  +0.02    57%
double_bottom (bull)          OOS     592 183.9  +0.01  -0.11  +0.02    46%     [-1.2,+1.3]  +0.03    58%
double_top (bear)             IS      680 113.7  +0.38  +0.61  +1.00    54%     [+0.1,+2.1]  -0.03    52%
double_top (bear)             OOS     447 138.8  -0.00  -0.09  -0.20    54%     [-1.3,+0.9]  -0.11    50%
falling_wedge (bull)          IS      609 101.8  +0.33  +0.26  +0.05    48%     [-1.0,+1.1]  +0.09    50%
falling_wedge (bull)          OOS     401 124.5  -0.13  -0.23  -0.25    46%     [-1.5,+0.8]  -0.07    45%
head_shoulders (bear)         IS      272  45.5  +0.24  +0.73  +0.82    58%     [-0.6,+2.3]  -0.04    45%
head_shoulders (bear)         OOS     181  56.2  +0.18  +0.03  +0.16    54%     [-1.3,+1.7]  -0.19    38%
inverse_head_shoulders (bull) IS      275  46.0  +0.06  -0.05  -0.19    45%     [-1.8,+1.3]  +0.08    49%
inverse_head_shoulders (bull) OOS     155  48.1  -0.32  -0.18  +1.15    52%     [-0.6,+2.9]  +0.14    56%
rectangle (bear)              IS      214  35.8  -0.02  -0.06  -0.79    48%     [-2.6,+0.8]  -0.18    50%
rectangle (bear)              OOS     133  41.3  +0.65  +0.73  +0.06    56%     [-2.1,+2.2]  -0.06    57%
rectangle (bull)              IS      264  44.2  -0.30  -0.89  -0.80    45%     [-2.3,+0.6]  +0.00    62%
rectangle (bull)              OOS     144  44.7  -0.40  -0.56  -1.38    40%     [-2.8,+0.0]  -0.06    60%
rising_wedge (bear)           IS      839 140.3  -0.32  -0.31  -0.44    51%     [-1.3,+0.4]  -0.11    43%
rising_wedge (bear)           OOS     433 134.5  -0.30  -0.55  -0.17    54%     [-1.3,+0.8]  -0.29    36%
symmetrical_triangle (bear)   IS      223  37.3  +0.29  +0.13  +0.77    55%     [-1.0,+2.8]  -0.12    31%
symmetrical_triangle (bear)   OOS     122  37.9  +0.55  +0.53  +0.72    60%     [-1.1,+2.9]  -0.20    26%
symmetrical_triangle (bull)   IS      300  50.2  +0.29  +0.37  +0.83    45%     [-0.9,+2.4]  +0.43    43%
symmetrical_triangle (bull)   OOS     118  36.6  -0.60  -0.36  -0.31    44%     [-2.1,+1.8]  +0.10    31%

-- verdicts (rule fixed in advance; 12 detectors tested) --
ascending_triangle (bull)         FAIL: IS mean <= 0; OOS 99% interval includes 0
bear_flag (bear)                  FAIL: IS mean <= 0; OOS mean <= 0; OOS 99% interval includes 0; OOS avg R <= 0
bull_flag (bull)                  FAIL: IS mean <= 0; OOS mean <= 0; OOS 99% interval includes 0
descending_triangle (bear)        FAIL: OOS 99% interval includes 0
double_bottom (bull)              FAIL: IS mean <= 0; OOS 99% interval includes 0
double_top (bear)                 FAIL: OOS mean <= 0; OOS 99% interval includes 0; OOS avg R <= 0
falling_wedge (bull)              FAIL: OOS mean <= 0; OOS 99% interval includes 0; OOS avg R <= 0
head_shoulders (bear)             FAIL: OOS 99% interval includes 0; OOS avg R <= 0
inverse_head_shoulders (bull)     FAIL: IS mean <= 0; OOS 99% interval includes 0
rectangle (bear)                  FAIL: IS mean <= 0; OOS 99% interval includes 0; OOS avg R <= 0
rectangle (bull)                  FAIL: IS mean <= 0; OOS mean <= 0; OOS 99% interval includes 0; OOS avg R <= 0
rising_wedge (bear)               FAIL: IS mean <= 0; OOS mean <= 0; OOS 99% interval includes 0; OOS avg R <= 0
symmetrical_triangle (bear)       FAIL: OOS 99% interval includes 0; OOS avg R <= 0
symmetrical_triangle (bull)       FAIL: OOS mean <= 0; OOS 99% interval includes 0

-- mean ex20 by year (n), %: only for patterns with >=150 events --
ascending_triangle_bull       2017:-1.5(13) 2018:-1.7(31) 2019:-0.8(35) 2020:-1.4(59) 2021:-4.6(35) 2022:-1.6(28) 2023:+1.6(36) 2024:+2.0(50) 2025:+1.0(42) 2026:+1.4(21)
bear_flag_bear                2017:-2.0(69) 2018:-0.8(314) 2019:-1.7(252) 2020:+0.2(206) 2021:+0.4(258) 2022:+0.3(280) 2023:-0.2(202) 2024:+0.5(241) 2025:-0.6(327) 2026:-0.9(336)
bull_flag_bull                2017:+0.1(121) 2018:-0.4(284) 2019:-1.1(267) 2020:-0.6(413) 2021:+0.0(381) 2022:+0.6(337) 2023:+0.0(474) 2024:-1.0(352) 2025:-0.1(284) 2026:-0.2(231)
descending_triangle_bear      2017:+5.0(6) 2018:-0.3(42) 2019:+2.1(36) 2020:-3.8(15) 2021:+1.1(33) 2022:+0.7(27) 2023:-0.7(22) 2024:-0.0(29) 2025:+0.5(39) 2026:+1.7(27)
double_bottom_bull            2017:-0.7(79) 2018:-1.3(136) 2019:+0.0(126) 2020:-0.6(152) 2021:-0.1(148) 2022:-0.3(165) 2023:+0.4(159) 2024:-1.2(198) 2025:+1.1(205) 2026:-0.1(123)
double_top_bear               2017:+0.3(34) 2018:+1.9(121) 2019:+0.2(138) 2020:+3.0(106) 2021:+0.5(107) 2022:-0.3(129) 2023:+1.5(78) 2024:-0.1(129) 2025:-0.9(162) 2026:+0.3(123)
falling_wedge_bull            2017:-0.4(35) 2018:-0.4(148) 2019:-0.9(94) 2020:+1.2(81) 2021:+1.0(84) 2022:-0.1(114) 2023:-0.7(82) 2024:-1.3(88) 2025:+1.2(147) 2026:-0.8(137)
head_shoulders_bear           2017:+2.3(16) 2018:+2.2(51) 2019:+1.2(29) 2020:+1.6(42) 2021:+0.8(55) 2022:-0.7(57) 2023:-0.6(35) 2024:+1.4(51) 2025:-0.4(64) 2026:-0.5(53)
inverse_head_shoulders_bull   2017:-1.6(17) 2018:+0.1(47) 2019:+0.6(47) 2020:+0.2(46) 2021:-0.6(28) 2022:-1.3(50) 2023:-0.3(48) 2024:+2.0(50) 2025:+0.2(58) 2026:+2.5(39)
rectangle_bear                2017:+2.9(7) 2018:-2.9(35) 2019:-2.4(44) 2020:-1.4(36) 2021:+2.2(33) 2022:-0.4(30) 2023:+0.2(41) 2024:-1.5(35) 2025:-0.2(40) 2026:+1.7(46)
rectangle_bull                2017:+1.4(18) 2018:-1.3(34) 2019:-0.9(59) 2020:-0.3(54) 2021:-3.3(41) 2022:+0.0(37) 2023:-0.3(37) 2024:-0.6(44) 2025:-1.0(46) 2026:-2.9(38)
rising_wedge_bear             2017:-2.6(44) 2018:+0.5(120) 2019:-1.5(120) 2020:-0.3(151) 2021:+0.5(155) 2022:-0.8(145) 2023:-1.0(170) 2024:-0.3(149) 2025:+0.6(126) 2026:+0.3(92)
symmetrical_triangle_bear     2017:+1.2(12) 2018:-0.5(48) 2019:+1.4(51) 2020:-1.5(32) 2021:+3.6(20) 2022:+1.7(40) 2023:+0.6(29) 2024:+1.8(43) 2025:+1.0(40) 2026:-0.9(30)
symmetrical_triangle_bull     2017:-1.5(21) 2018:+1.2(39) 2019:+0.0(44) 2020:+3.4(67) 2021:+0.1(56) 2022:+0.6(53) 2023:-1.5(34) 2024:+0.4(33) 2025:+0.1(43) 2026:-1.5(28)
```
