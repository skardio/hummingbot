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

    def hot_cold_table(self, top_n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
        main_counts, euro_counts = self.number_frequencies()
        main_df = pd.DataFrame({"number": main_counts.index, "count": main_counts.values})
        euro_df = pd.DataFrame({"number": euro_counts.index, "count": euro_counts.values})
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
                euro_df.sort_values(["count", "number"], ascending=[False, True])
                .head(top_n)
                .assign(group="hot_euro"),
                euro_df.sort_values(["count", "number"], ascending=[True, True])
                .head(top_n)
                .assign(group="cold_euro"),
            ],
            ignore_index=True,
        )
        return main_ranked, euro_ranked
