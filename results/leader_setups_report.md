```
Leader setups: 364 stocks, trades 2017-11-06 to 2026-10-28, split 2023-09-06, leaders = top 20 of liquid top 200 above 200-DMA by 12-1, cost 0.3%
Exit: stop 2.0xATR, trail 3.0xATR from highest close, time stop 60d. R net of cost, 1R = 2xATR.

variant               per       n   win%   avg R95% (month boot)    PF  bars   ret/tr vs ctrl
-- leader stocks --
ctrl_leader           IS     1599    40%   +0.31   [+0.14,+0.51]  1.58    25   +2.78%        
ctrl_leader           OOS     959    31%   -0.02   [-0.24,+0.23]  0.97    21   +0.31%        
breakout55@leader     IS      446    37%   +0.30   [+0.04,+0.52]  1.53    18   +1.97%   -0.01
breakout55@leader     OOS     248    31%   -0.06   [-0.30,+0.16]  0.91    15   -0.49%   -0.04
pullback20@leader     IS     1085    41%   +0.32   [+0.13,+0.50]  1.61    24   +2.71%   +0.01
pullback20@leader     OOS     608    30%   -0.04   [-0.26,+0.21]  0.93    20   +0.01%   -0.03
-- other stocks --
ctrl_other            IS     5656    37%   +0.16   [-0.01,+0.32]  1.29    24   +1.16%        
ctrl_other            OOS    3477    34%   +0.08   [-0.16,+0.34]  1.14    23   +0.74%        
breakout55@other      IS     1946    34%   +0.13   [-0.05,+0.29]  1.22    19   +0.83%   -0.03
breakout55@other      OOS    1194    32%   +0.04   [-0.19,+0.30]  1.07    18   +0.42%   -0.04
pullback20@other      IS     4342    37%   +0.19   [+0.03,+0.34]  1.33    23   +1.17%   +0.02
pullback20@other      OOS    2682    34%   +0.09   [-0.18,+0.39]  1.16    22   +0.64%   +0.01

-- avg R by signal year (n) --
breakout55@leader     2017:+0.13(15) 2018:-0.32(65) 2019:-0.13(63) 2020:+0.31(89) 2021:+0.47(84) 2022:+0.30(65) 2023:+0.96(95) 2024:-0.17(88) 2025:-0.01(61) 2026:-0.25(69)
breakout55@other      2017:-0.13(70) 2018:-0.08(192) 2019:-0.13(215) 2020:+0.35(358) 2021:+0.21(562) 2022:-0.23(243) 2023:+0.51(539) 2024:-0.07(508) 2025:+0.04(241) 2026:-0.37(212)
ctrl_leader           2017:+0.34(58) 2018:-0.11(260) 2019:+0.23(288) 2020:+0.54(287) 2021:+0.31(255) 2022:+0.03(283) 2023:+1.21(248) 2024:-0.13(296) 2025:-0.20(353) 2026:-0.05(230)
ctrl_other            2017:-0.10(312) 2018:-0.21(690) 2019:+0.02(712) 2020:+0.40(931) 2021:+0.31(1439) 2022:-0.19(872) 2023:+0.88(1146) 2024:+0.03(1355) 2025:-0.05(851) 2026:-0.35(825)
pullback20@leader     2017:+0.44(41) 2018:-0.13(171) 2019:+0.12(195) 2020:+0.68(177) 2021:+0.36(184) 2022:+0.01(188) 2023:+1.09(192) 2024:-0.09(179) 2025:-0.32(206) 2026:-0.08(160)
pullback20@other      2017:-0.00(225) 2018:-0.15(504) 2019:+0.07(535) 2020:+0.47(691) 2021:+0.30(1165) 2022:-0.22(651) 2023:+0.81(962) 2024:-0.01(1073) 2025:-0.09(675) 2026:-0.28(543)

-- verdicts (rule fixed in advance) --
breakout55@leader     FAIL: OOS avg R <= 0; does not beat matched control OOS; OOS interval includes 0
pullback20@leader     FAIL: OOS avg R <= 0; does not beat matched control OOS; OOS interval includes 0
breakout55@other      FAIL: does not beat matched control OOS; OOS interval includes 0
pullback20@other      FAIL: OOS interval includes 0
```
