```
Research: 48 tickers, trades 2017-11-06 to 2026-10-19, IS/OOS split 2023-08-31, cost 0.3% round trip
Exit: stop 2.0xATR, trail 3.0xATR from highest close, time stop 60d. R = net of cost; 1R = 2xATR.

variant               per       n   win%   avg R95% (month boot)    PF  bars   ret/tr vs ctrl
-- controls: same exits on every eligible day --
ctrl_above50          IS     1616    40%   +0.30   [+0.10,+0.50]  1.54    23   +2.45%        
ctrl_above50          OOS     982    32%   +0.03   [-0.18,+0.25]  1.05    21   +0.44%        
ctrl_above50+mkt      IS     1521    39%   +0.25   [+0.02,+0.47]  1.43    22   +1.91%        
ctrl_above50+mkt      OOS     723    34%   +0.09   [-0.12,+0.33]  1.16    21   +0.77%        
ctrl_uptrend          IS     1324    40%   +0.28   [+0.06,+0.48]  1.49    24   +2.42%        
ctrl_uptrend          OOS     832    35%   +0.13   [-0.10,+0.39]  1.23    22   +1.23%        
ctrl_uptrend+mkt      IS     1240    40%   +0.28   [+0.04,+0.51]  1.48    23   +2.25%        
ctrl_uptrend+mkt      OOS     653    37%   +0.22   [-0.05,+0.53]  1.41    23   +1.71%        
-- setups --
breakout55            IS      475    37%   +0.34   [+0.09,+0.61]  1.61    18   +2.37%   +0.06
breakout55            OOS     314    32%   -0.00   [-0.25,+0.25]  1.00    17   +0.04%   -0.13
breakout55+mkt        IS      451    36%   +0.33   [+0.08,+0.60]  1.58    18   +2.30%   +0.06
breakout55+mkt        OOS     269    32%   +0.03   [-0.24,+0.32]  1.04    16   +0.07%   -0.20
pullback20            IS     1023    41%   +0.30   [+0.03,+0.55]  1.50    23   +2.67%   +0.02
pullback20            OOS     671    35%   +0.12   [-0.12,+0.41]  1.20    20   +0.85%   -0.01
pullback20+mkt        IS      957    40%   +0.29   [+0.00,+0.55]  1.48    22   +2.38%   +0.02
pullback20+mkt        OOS     553    36%   +0.15   [-0.12,+0.50]  1.26    21   +0.97%   -0.07
rs_breakout           IS      436    38%   +0.40   [+0.16,+0.62]  1.74    20   +2.91%   +0.10
rs_breakout           OOS     262    33%   +0.09   [-0.18,+0.40]  1.14    19   +0.56%   +0.06
rs_breakout+mkt       IS      385    37%   +0.36   [+0.12,+0.60]  1.66    19   +2.51%   +0.12
rs_breakout+mkt       OOS     197    34%   +0.15   [-0.20,+0.55]  1.24    18   +0.77%   +0.05

-- avg R by signal year (n) --
breakout55            2017: -0.22 (15)  2018: -0.23 (50)  2019: +0.02 (63)  2020: +0.58 (77)  2021: +0.54 (131)  2022: +0.14 (80)  2023: +0.80 (121)  2024: -0.25 (123)  2025: +0.09 (68)  2026: -0.34 (61)
breakout55+mkt        2017: -0.22 (15)  2018: -0.23 (47)  2019: -0.01 (58)  2020: +0.48 (70)  2021: +0.54 (131)  2022: +0.12 (72)  2023: +0.81 (120)  2024: -0.25 (123)  2025: +0.16 (62)  2026: -0.81 (22)
pullback20            2017: +0.10 (53)  2018: -0.16 (129)  2019: -0.47 (123)  2020: +0.74 (159)  2021: +0.57 (253)  2022: +0.05 (180)  2023: +0.91 (232)  2024: -0.05 (264)  2025: +0.24 (153)  2026: -0.26 (148)
pullback20+mkt        2017: +0.10 (53)  2018: -0.17 (115)  2019: -0.59 (117)  2020: +0.69 (145)  2021: +0.57 (253)  2022: +0.05 (151)  2023: +0.91 (229)  2024: -0.05 (261)  2025: +0.18 (141)  2026: -0.57 (45)
rs_breakout           2017: -0.23 (10)  2018: -0.04 (58)  2019: +0.12 (69)  2020: +0.47 (82)  2021: +0.59 (80)  2022: +0.31 (84)  2023: +1.11 (82)  2024: -0.29 (83)  2025: +0.44 (81)  2026: -0.31 (69)
rs_breakout+mkt       2017: -0.23 (10)  2018: -0.10 (52)  2019: +0.04 (61)  2020: +0.28 (65)  2021: +0.59 (80)  2022: +0.36 (66)  2023: +1.11 (80)  2024: -0.28 (82)  2025: +0.62 (64)  2026: -0.91 (22)

-- verdicts (rule fixed in advance) --
breakout55            FAIL: OOS avg R <= 0; does not beat matched control OOS; OOS interval includes 0
breakout55+mkt        FAIL: does not beat matched control OOS; OOS interval includes 0
pullback20            FAIL: does not beat matched control OOS; OOS interval includes 0
pullback20+mkt        FAIL: does not beat matched control OOS; OOS interval includes 0
rs_breakout           FAIL: OOS interval includes 0
rs_breakout+mkt       FAIL: OOS interval includes 0

Exit reasons (setups): stop 5630, time 363
```
