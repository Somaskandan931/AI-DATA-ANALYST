# Auto-EDA report

Source file: electricity\_demand.csv  
Dataset fingerprint (SHA-256): `e0b688d65789cee9cd2f0bee7581a9d4339d5b29a1a902501eb5f20b052a5354`  
8 warnings (see section 5)

## 1. Dataset overview

- **Rows:** 485
- **Columns:** 6
- **Duplicate rows:** 5

*Schema and quality profile of the uploaded data*

| Column | Type | Missing | Missing (%) | Distinct | Min | Max | Mean | Median | Std | Q1 | Q3 | Outliers (IQR) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| record\_id | string | 0 | 0.0 | 480 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| date | date | 0 | 0.0 | 120 | 2025-01-01 | 2025-04-30 | n/a | n/a | n/a | n/a | n/a | n/a |
| region | string | 0 | 0.0 | 4 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| demand\_mwh | float | 4 | 0.8 | 460 | 740.5 | 3950.8 | 1121.197713 | 1106.7 | 279.334266 | 960.7 | 1240.8 | 3 |
| temperature\_c | float | 12 | 2.5 | 171 | 9.4 | 31.3 | 19.528118 | 19.4 | 4.564889 | 16.1 | 22.9 | 0 |
| holiday | string | 0 | 0.0 | 2 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## 2. Methods

### Step 1: Summary statistics

For each selected numeric column: count, missing count, mean, sample standard deviation (ddof=1), minimum, quartiles (linear interpolation) and maximum, computed over the non-missing values.

- **Columns:** demand\_mwh, temperature\_c
- **Rows in the analysed data:** 480
- **Rows contributing:** 480

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 2: Distribution

Histogram of a numeric column with equal-width bins from minimum to maximum.

- **Columns:** demand\_mwh
- **column:** demand\_mwh
- **bins:** 8
- **top\_n:** 10
- **Rows in the analysed data:** 480
- **Rows contributing:** 480

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 3: Distribution

Counts of the most frequent values of a non-numeric column.

- **Columns:** region
- **column:** region
- **bins:** 10
- **top\_n:** 10
- **Rows in the analysed data:** 480
- **Rows contributing:** 480

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 4: Grouped aggregation

Rows are grouped by the key columns (rows with a missing key are excluded) and the chosen aggregations of the value column are computed for each group.

- **Columns:** region, demand\_mwh
- **group\_by:** region
- **value\_column:** demand\_mwh
- **aggregations:** mean, count
- **max\_groups:** 50
- **Rows in the analysed data:** 480
- **Rows contributing:** 480

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 5: Correlation

Pairwise correlation (Pearson or Spearman, as set in the parameters) between the selected numeric columns; each pair uses the rows where both values exist.

- **Columns:** demand\_mwh, temperature\_c
- **method:** pearson
- **Rows in the analysed data:** 480
- **Rows contributing:** 468

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 6: Outlier summary

Values outside \[Q1 - f x IQR, Q3 + f x IQR\] are counted as candidate outliers, with f set in the parameters and quartiles by linear interpolation. Nothing is removed.

- **Columns:** demand\_mwh, temperature\_c
- **iqr\_factor:** 1.5
- **Rows in the analysed data:** 480
- **Rows contributing:** 480

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 7: K-means clustering

k-means clustering (Lloyd's algorithm, scikit-learn) of the rows with no missing value in the selected columns. Columns are standardized first unless disabled; clusters are numbered largest first and centroids are reported in original units.

- **Columns:** demand\_mwh, temperature\_c
- **k:** 3
- **standardize:** yes
- **random\_state:** 0
- **Rows in the analysed data:** 480
- **Rows contributing:** 468

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

### Step 8: Principal component analysis

Principal component analysis (scikit-learn, full SVD) of the rows with no missing value in the selected columns. Columns are standardized first unless disabled. The sign of each component is fixed so that its largest-magnitude loading is positive.

- **Columns:** demand\_mwh, temperature\_c
- **n\_components:** 2
- **standardize:** yes
- **Rows in the analysed data:** 480
- **Rows contributing:** 468

Cleaning applied before this step:

- Removed 5 duplicate rows (kept the first occurrence)
- Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

## 3. Results

### Step 1: Summary statistics

- **Rows used:** 480

*Statistics over non-missing values*

| Column | Count | Missing | Mean | Std | Min | Q1 | Median | Q3 | Max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| demand\_mwh | 480 | 0 | 1121.561458 | 279.102722 | 740.5 | 960.925 | 1107.4 | 1240.5 | 3950.8 |
| temperature\_c | 468 | 12 | 19.549573 | 4.57045 | 9.4 | 16.175 | 19.4 | 22.9 | 31.3 |

### Step 2: Distribution

- **Column:** demand\_mwh
- **Missing values excluded:** 0
- **Rows used:** 480

*Equal-width bins; the last bin includes its upper edge*

| Bin | Rows |
| --- | --- |
| 740.5 to 1141.7875 | 280 |
| 1141.7875 to 1543.075 | 197 |
| 1543.075 to 1944.3625 | 0 |
| 1944.3625 to 2345.65 | 0 |
| 2345.65 to 2746.9375 | 0 |
| 2746.9375 to 3148.225 | 0 |
| 3148.225 to 3549.5125 | 0 |
| 3549.5125 to 3950.8 | 3 |

Charts for this step: Figure 1

### Step 3: Distribution

- **Column:** region
- **Missing values excluded:** 0
- **Distinct values:** 4
- **Rows used:** 480

*Most frequent values*

| region | Rows |
| --- | --- |
| East | 120 |
| North | 120 |
| South | 120 |
| West | 120 |

Charts for this step: Figure 2

### Step 4: Grouped aggregation

- **Total groups:** 4
- **Groups shown:** 4
- **Rows used:** 480

*Aggregations of demand\_mwh, sorted by group key*

| region | mean of demand\_mwh | count of demand\_mwh |
| --- | --- | --- |
| East | 883.820833 | 120 |
| North | 1094.201667 | 120 |
| South | 1321.874167 | 120 |
| West | 1186.349167 | 120 |

Charts for this step: Figure 3, Figure 4

### Step 5: Correlation

- **Method:** Pearson
- **Rows used:** 468

*Pearson correlation*

|  | demand\_mwh | temperature\_c |
| --- | --- | --- |
| demand\_mwh | 1 | 0.140038 |
| temperature\_c | 0.140038 | 1 |

*Rows where both values exist*

|  | demand\_mwh | temperature\_c |
| --- | --- | --- |
| demand\_mwh | 480 | 468 |
| temperature\_c | 468 | 468 |

Charts for this step: Figure 5

### Step 6: Outlier summary

- **IQR factor:** 1.5
- **Rows used:** 480

*Candidate outliers by the IQR rule (nothing is removed)*

| Column | Count | Q1 | Q3 | Lower bound | Upper bound | Below | Above | Outliers | Fraction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| demand\_mwh | 480 | 960.925 | 1240.5 | 541.5625 | 1659.8625 | 0 | 3 | 3 | 0.00625 |
| temperature\_c | 468 | 16.175 | 22.9 | 6.0875 | 32.9875 | 0 | 0 | 0 | 0 |

Charts for this step: Figure 6

### Step 7: K-means clustering

- **Clusters (k):** 3
- **Rows clustered:** 468
- **Columns standardized:** yes
- **Random seed:** 0
- **Inertia (standardized units):** 318.971117
- **Iterations:** 8
- **Silhouette:** 0.42717
- **Rows used:** 468

*Clusters, largest first; centroids are column means in original units*

| Cluster | Size | Fraction | Mean of demand\_mwh | Mean of temperature\_c |
| --- | --- | --- | --- | --- |
| 0 | 254 | 0.542735 | 1064.253937 | 16.11378 |
| 1 | 211 | 0.450855 | 1150.816588 | 23.645024 |
| 2 | 3 | 0.00641 | 3880.1 | 22.4 |

Charts for this step: Figure 7

### Step 8: Principal component analysis

- **Components:** 2
- **Rows used:** 468
- **Columns standardized:** yes
- **Total variance:** 2.004283
- **Rows used:** 468

*Variance explained*

| Component | Explained variance | Ratio | Cumulative ratio |
| --- | --- | --- | --- |
| PC1 | 1.14248 | 0.570019 | 0.570019 |
| PC2 | 0.861803 | 0.429981 | 1 |

*Loadings (weight of each column in each component)*

| Column | PC1 | PC2 |
| --- | --- | --- |
| demand\_mwh | 0.707107 | 0.707107 |
| temperature\_c | 0.707107 | -0.707107 |

Charts for this step: Figure 8

## 4. Charts

### Figure 1. Distribution of demand\_mwh

Columns: demand\_mwh \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 2 (distribution), artifact `dda317205b6a`

*Plotted values (x: demand\_mwh; y: Rows)*

| demand\_mwh | Rows |
| --- | --- |
| 740.5 to 1141.79 | 280 |
| 1141.79 to 1543.08 | 197 |
| 1543.08 to 1944.36 | 0 |
| 1944.36 to 2345.65 | 0 |
| 2345.65 to 2746.94 | 0 |
| 2746.94 to 3148.22 | 0 |
| 3148.22 to 3549.51 | 0 |
| 3549.51 to 3950.8 | 3 |

### Figure 2. Most frequent values of region

Columns: region \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 3 (distribution), artifact `be49abeea40d`

*Plotted values (x: region; y: Rows)*

| region | Rows |
| --- | --- |
| East | 120 |
| North | 120 |
| South | 120 |
| West | 120 |

### Figure 3. Mean of demand\_mwh by region

Columns: region, demand\_mwh \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 4 (grouped\_aggregation), artifact `abc2298eca1a`

*Plotted values (x: region; y: mean of demand\_mwh)*

| region | mean of demand\_mwh |
| --- | --- |
| East | 883.820833 |
| North | 1094.201667 |
| South | 1321.874167 |
| West | 1186.349167 |

### Figure 4. Count of demand\_mwh by region

Columns: region, demand\_mwh \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 4 (grouped\_aggregation), artifact `abc2298eca1a`

*Plotted values (x: region; y: count of demand\_mwh)*

| region | count of demand\_mwh |
| --- | --- |
| East | 120 |
| North | 120 |
| South | 120 |
| West | 120 |

### Figure 5. Pearson correlation

Columns: demand\_mwh, temperature\_c \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 5 (correlation), artifact `d42f60cf6ac0`

Warning: pairs with a missing value are excluded pairwise  
*Plotted values (Column by Column)*

|  | demand\_mwh | temperature\_c |
| --- | --- | --- |
| demand\_mwh | 1 | 0.140038 |
| temperature\_c | 0.140038 | 1 |

### Figure 6. Outlier fraction by column (IQR factor 1.5)

Columns: demand\_mwh, temperature\_c \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 6 (outlier\_summary), artifact `5c9f5291a550`

*Plotted values (x: Column; y: Fraction of rows outside the IQR bounds)*

| Column | Fraction of rows outside the IQR bounds |
| --- | --- |
| demand\_mwh | 0.00625 |
| temperature\_c | 0 |

### Figure 7. Cluster sizes (k=3)

Columns: demand\_mwh, temperature\_c \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 7 (clustering), artifact `7ae35ad8e9b7`

Warning: 12 rows with a missing value in the selected columns were excluded  
*Plotted values (x: Cluster (largest first); y: Rows)*

| Cluster (largest first) | Rows |
| --- | --- |
| Cluster 0 | 254 |
| Cluster 1 | 211 |
| Cluster 2 | 3 |

### Figure 8. Variance explained by each principal component

Columns: demand\_mwh, temperature\_c \| Cleaning: Removed 5 duplicate rows (kept the first occurrence); Filled 4 missing values in 'demand\_mwh' with the median (1107.4)

Source: step 8 (pca), artifact `50055c816e8d`

Warning: 12 rows with a missing value in the selected columns were excluded  
*Plotted values (x: Component; y: Share of total variance)*

| Component | Share of total variance |
| --- | --- |
| PC1 | 0.570019 |
| PC2 | 0.429981 |

## 5. Warnings

- **Dataset:** 5 duplicate rows (1.0% of rows) are present
- **Dataset:** Column 'demand\_mwh' has 4 missing values (0.8%)
- **Dataset:** Column 'temperature\_c' has 12 missing values (2.5%)
- **Dataset:** Column 'demand\_mwh' has 3 candidate outliers by the IQR rule
- **Step 1 (Summary statistics):** temperature\_c: 12 missing values excluded
- **Step 5 (Correlation):** pairs with a missing value are excluded pairwise
- **Step 7 (K-means clustering):** 12 rows with a missing value in the selected columns were excluded
- **Step 8 (Principal component analysis):** 12 rows with a missing value in the selected columns were excluded

## 6. Limitations

- All numbers describe this one uploaded file. They say nothing about data that was not uploaded, and they do not show that one thing causes another.
- Column types are inferred from the text in the file, and units are not known. Check that each inferred type matches what the column means.
- Values are rounded to six decimal places where they were computed.
- Results for the steps that list cleaning were computed on a cleaned copy of the data, not on the data as uploaded. Dropping rows can change who is represented, and filling in missing values makes a column look less variable than it is.
- Correlation measures one kind of association between two columns (linear for Pearson, monotonic for Spearman). A value near zero does not rule out other relationships.
- Outliers here are values outside the IQR bounds. They are candidates to look at, not errors, and they were not removed.
- k-means assumes compact, similarly sized groups and is sensitive to column scale and to the chosen k. Cluster numbers are only labels, and the clusters are not validated against any ground truth.
- PCA finds linear combinations of the selected columns. Components are summaries of variance, not necessarily meaningful quantities, and standardizing or not changes the result.
- Grouped results and category counts can be cut to the largest or first entries; a warning says so whenever that happened.
- The report is generated by fixed code from computed results. It contains no model-written text, and it does not interpret the findings.

## 7. Reproducibility

- **Report schema:** 1.0
- **Profile schema:** 1.0
- **Analysis schema:** 1.0
- **Chart schema:** 1.0
- **Libraries:** numpy 2.4.4, pandas 3.0.2, scikit-learn 1.8.0, scipy 1.17.1

Re-running the same plan on the same file with the same library versions gives the same numbers.
