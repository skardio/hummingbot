from __future__ import annotations

import pandas as pd

from .database import DrawDatabase


class EuroAnalyzer:
    def __init__(self, database: DrawDatabase) -> None:
        self.database = database

    def dataframe(self) -> pd.DataFrame:
        return self.database.load_dataframe()

    def number_frequencies(self) -> tuple[pd.Series, pd.Series]:
        df = self.dataframe()
        main_counts = pd.Series(0, index=range(1, 51), dtype="int64")
        euro_counts = pd.Series(0, index=range(1, 13), dtype="int64")

        if df.empty:
            return main_counts, euro_counts

        for col in [f"main_{idx}" for idx in range(1, 6)]:
            main_counts = main_counts.add(df[col].value_counts(), fill_value=0).astype("int64")

        for col in [f"euro_{idx}" for idx in range(1, 3)]:
            euro_counts = euro_counts.add(df[col].value_counts(), fill_value=0).astype("int64")

        return main_counts.sort_index(), euro_counts.sort_index()

    def _euro_pool_sizes_by_year(self, df: pd.DataFrame) -> pd.Series:
        """Infer the per-year euro-number pool size (Eurojackpot expanded it over time:
        1-8 -> 1-10 -> 1-12). Uses the highest euro number actually drawn each year,
        then takes a running max across years so a number that was eligible but not
        yet drawn in its introduction year isn't mistaken for "not yet introduced".
        """
        if df.empty:
            return pd.Series(dtype="int64")
        year_max = df.groupby("source_year")[["euro_1", "euro_2"]].max().max(axis=1)
        return year_max.sort_index().cummax().astype("int64")

    def euro_eligible_draws(self) -> pd.Series:
        """Number of draws in which each euro number (1-12) was part of the active pool."""
        df = self.dataframe()
        eligible = pd.Series(0, index=range(1, 13), dtype="int64")
        if df.empty:
            return eligible
        pool_by_year = self._euro_pool_sizes_by_year(df)
        draws_per_year = df.groupby("source_year").size()
        for number in eligible.index:
            eligible_years = pool_by_year[pool_by_year >= number].index
            eligible[number] = int(draws_per_year.reindex(eligible_years, fill_value=0).sum())
        return eligible

    def euro_number_rates(self) -> pd.Series:
        """Euro-number draw frequency relative to draws where that number was possible.

        Raw counts over the full history are misleading: numbers 9-12 only became
        possible after later pool expansions, so they naturally have fewer hits
        without being statistically "cold".
        """
        _, euro_counts = self.number_frequencies()
        eligible = self.euro_eligible_draws()
        rates = pd.Series(0.0, index=euro_counts.index)
        mask = eligible > 0
        rates[mask] = euro_counts[mask] / eligible[mask]
        return rates

    def hot_cold_table(self, top_n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
        main_counts, euro_counts = self.number_frequencies()
        euro_eligible = self.euro_eligible_draws()
        euro_rates = self.euro_number_rates()

        main_df = pd.DataFrame({"number": main_counts.index, "count": main_counts.values})
        euro_df = pd.DataFrame(
            {
                "number": euro_counts.index,
                "count": euro_counts.values,
                "eligible_draws": euro_eligible.values,
                "rate": euro_rates.round(4).values,
            }
        )
        main_ranked = pd.concat(
            [
                main_df.sort_values(["count", "number"], ascending=[False, True])
                .head(top_n)
                .assign(group="hot_main"),
                main_df.sort_values(["count", "number"], ascending=[True, True])
                .head(top_n)
                .assign(group="cold_main"),
            ],
            ignore_index=True,
        )
        euro_ranked = pd.concat(
            [
                euro_df.sort_values(["rate", "number"], ascending=[False, True])
                .head(top_n)
                .assign(group="hot_euro"),
                euro_df.sort_values(["rate", "number"], ascending=[True, True])
                .head(top_n)
                .assign(group="cold_euro"),
            ],
            ignore_index=True,
        )
        return main_ranked, euro_ranked
