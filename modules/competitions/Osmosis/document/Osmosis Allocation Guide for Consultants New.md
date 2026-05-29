---
title: "Osmosis Allocation Guide for Consultants New"
source: "https://platform.worldquantbrain.com/learn/documentation/consultant-information/osmosis-allocation-guide-consultants"
author:
published:
created: 2026-05-09
description: "The platform that helps you Learn, Earn and Grow in the field of Quantitative Finance."
tags:
  - "clippings"
---
What is Osmosis?

Osmosis is your **personal combo of Alphas**, built from the **points you allocate** across your Alpha pool in different scopes (region x delay). The Platform then:

- Computes the PNL of this combination of Alphas every day
- Uses this combo performance:
	- As a theme multiplier in daily **base payment**
		- As [**Combined Osmosis Performance**](https://platform.worldquantbrain.com/genius/) in Genius to help inform **quarterly payments**
		- As Daily Osmosis Rank metric on the [**leaderboard**](https://platform.worldquantbrain.com/competition/consultant)

How to allocate points?

1\. Use the Properties section on the Alphas' page to allocate Osmosis points to Alphas:

![Picture3.png](https://api.worldquantbrain.com/content/images/0W6oUj1dLWqdu1BIyiuiAmx35vY=/455/original/Picture3.png)

1. Use the Submitted Alphas table to edit Osmosis points directly

![Osmosis 1.png](https://api.worldquantbrain.com/content/images/DV3xTsEJ0CKYiTgOgOvUHK7x1Nw=/457/original/Osmosis_1.png)

Hover over the Osmosis Points cell for any Alpha: you will see a text cursor and an edit icon appear. Click and update your Osmosis Points value directly inline. After saving:

- ✅A green check mark confirms the update was successful. It does not mean that you have allocated the right number of points or Alphas across scopes
- ❗A red warning icon appears if the update failed, along with a tooltip explaining the reason

Hover over the green preview icon in the leftmost column to view the Alpha expression.

Allocation Requirements

You need to allocate Osmosis points each to at least 3 scopes (regionxdelay combinations allowed by your Genius level). Within each scope, you need to allocate exactly 100k points to at least 10 Alphas.

You can allocate to

- All types of Alphas: regular, Atom, Power Pool, SuperAlphas etc
- Alphas submitted at any date, not just recent submissions

No minimum per Alpha, but total allocation per scope must equal 100,000 points.

**Points lock weekly**

- Your allocations as of every **Sunday 23:59 hrs EST** are then used for **all daily combo calculations after 7 days**.
	- Example: points that lock in on 8th Feb 2026 (Sunday) will be used for the [daily combo calculations](https://platform.worldquantbrain.com/competition/consultant) starting from 16th Feb to 22nd Feb.
- You can change points anytime. There is no penalty for changing allocations multiple times, but only the **allocations** **as of Sunday night** are used.

![Osmosis 3.png](https://api.worldquantbrain.com/content/images/tEa6Cjv7VkwWMTUcvqFJwMQvcnQ=/459/original/Osmosis_3.png)

Where can you see your Osmosis allocation?

- On the [Genius Status Page](https://platform.worldquantbrain.com/genius/status) > Osmosis Allocation

![Picture2.png](https://api.worldquantbrain.com/content/images/tSy3W_gwIkuWJYkAe6HEPvxA-Ps=/454/original/Picture2.png)

- On the [Genius Status Page](https://platform.worldquantbrain.com/genius/status) > Combined Osmosis Performance: It shows your long‑term after‑cost Sharpe from stitching weekly Osmosis combos over the Genius quarter.
- As Daily Osmosis Rank on [Consultant Leaderboard](https://platform.worldquantbrain.com/competition/consultant): It is the Rank of one day’s PNL of your Osmosis Combo across all consultants, updated daily using your Osmosis allocation from two Sundays ago. It will remain blank if you don’t have a valid allocation.

Daily Osmosis Rank (base payments)

- For each scope (regionxdelay), with your Osmosis points allocation from two Sundays ago, the Platform computes one day’s PNL (from 2 years ago in the out-sample period)
- Then ranks each scope’s PNL among consultants, to get your scope rank
- Next, calculates average of all your scope ranks. This average is your Daily Osmosis Rank, which is applied as a quality factor multiplier for your daily base payment. Value of the multiplier ranges between 1 and 2 and is updated daily
- Averaging only considers scopes where you've allocated points (not all possible scopes).
- Performance is not proportional to number of scopes, though variety helps minimize drawdowns. Diversifying across regions helps with portfolio robustness.

Combined Osmosis Performance (Genius combo)

- Each Sunday’s Osmosis allocation generates your after-cost PNL. All your after-cost PNLs across Sundays are combined to generate after-cost Sharpe for the quarter, which is the Combined Osmosis Performance.
- Updated every 4-6 weeks.
- You need to have a correct allocation of points for at least 6 weeks in previous 3-months to be eligible for getting a Combined Osmosis Performance

Max of Combined Alpha Performance, Combined Selected Alphas Performance, Combined Power Pool Alpha Performance and Combined Osmosis Performance is used in the Genius eligibility criteria.

Actionable tips for potentially building a good Osmosis combo

- **Start with your best Alphas:** Prioritize Alphas with unique ideas, no random mixing of expressions. Don’t waste points on Alphas that don't have a strong economic rationale.
	- **Diversify across scopes:** Use more than the bare minimum of 3 scopes when possible.

Mix major scopes (e.g., USA, GLB) with others where you have strong Alphas. Allocate many Alphas in regions that have been prioritized in opportunity webinars. Check the [Osmosis Allocation table](https://platform.worldquantbrain.com/genius/status#:~:text=Osmosis%20Allocation%20\(min%203%20scopes\)) for balance points remaining to be allocated.

- - **Diversify across datasets**: Avoid concentration in specific datasets or category. Cover many datasets and categories to avoid large drawdowns. Occam's Razor: If you have multiple submissions on the same dataset using the same idea, prioritize the simpler one with strongest economic rationale
		- **Diversify across Operators and Neutralizations:** Each operator or neutralization has nuances. Overexposure to one can cause all your Alphas to drawdown together and led to negative returns in Combined Osmosis Performance.
		- **Control volatility:** Concentrated combos can create big swings. Aim for steady positive returns with reasonable risk**.**
		- **Avoid frequent radical reshuffles:** Use gradual adjustments and evaluate over weeks, not days. So you can track impact of your adjustments.
- Use **SuperAlpha selection table** to analyze a large pool of Alphas. This will help you diversify your signals across Datasets, Dataset categories, Turnover ranges and Alpha ideas
- Add a custom tag to your important Alphas, so you can filter them quickly later
- Exclude Alphas whose Sharpe ratio declines by approximately 60% or more after investability constraints are applied, except when:  
	\- the Alpha is unique within the selection, or  
	\- the Alpha is based on a different dataset
- Classify Alphas by turnover into buckets: <10%, 10–20%, and >20%; avoid alphas with turnover above 20% unless their investability-constrained Sharpe remains robust
- Re-run simulations for previously submitted Alphas without MaxTradeOn by enabling MaxTradeOn; retain these Alphas only if their performance remains satisfactory
- Use Alphas lists to evaluate intra-set correlations and eliminate Alphas that exhibit high mutual correlation
- Examine individual PnL profiles and remove Alphas that experience drawdowns concurrently with others
- Apply SuperAlpha to the shortlisted set and assess the combined Sharpe ratio after investability constraints and MaxTradeOn are incorporated
- Consider high-quality legacy Alphas developed prior to PowerPool or Atom; the Osmosis Alpha set is not limited to those newer Alpha types
- Aim to include a larger number of high-quality Alphas, as this generally enhances Osmosis combination performance