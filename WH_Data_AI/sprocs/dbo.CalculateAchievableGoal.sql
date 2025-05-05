-- =============================================
-- Author:      <Author,,Name>
-- Create date: <Create Date,,>
-- Description: Calculates a suggested achievable goal for a given metric based on historical data.
--              It analyzes historical trends, calculates statistical bounds, and projects
--              a goal along with monthly targets to reach it.
--
-- Parameters:
--   @MetricName: VARCHAR(50) - The name of the metric in the HistoricalMetrics table to analyze.
--   @ConfidenceLevel: FLOAT (default 0.7) - The statistical confidence level (e.g., 0.7, 0.8, 0.9, 0.95)
--                                            used to calculate the upper bound.
--   @ImprovementFactor: FLOAT (default 1.1) - A multiplier applied to the calculated bound or historical max
--                                             to set the final goal (e.g., 1.1 = 10% improvement target).
--
-- Returns:     Three result sets:
--              1. Baseline Metrics: Mean, Median, StdDev, Min, Max, Trend of historical data.
--              2. Goal Metrics: Suggested Goal, Confidence Level used, Improvement Factor used.
--              3. Monthly Targets: A 12-month breakdown of targets to reach the suggested goal.
--
-- Requires:    A table named 'HistoricalMetrics' with columns:
--              - MetricName (VARCHAR)
--              - MetricValue (suitable numeric type, e.g., FLOAT, DECIMAL)
--              - MetricDate (suitable date/datetime type)
-- =============================================
CREATE PROCEDURE [dbo].[CalculateAchievableGoal]
    @MetricName VARCHAR(50),
    @ConfidenceLevel FLOAT = 0.7,    -- Default to 70% confidence
    @ImprovementFactor FLOAT = 1.1   -- Default to 10% improvement target
AS
BEGIN
    SET NOCOUNT ON; -- Prevents sending DONE_IN_PROC messages

    -- =========================================================================
    -- Variable Declarations
    -- =========================================================================
    DECLARE @Mean FLOAT,
            @StdDev FLOAT,
            @Median FLOAT,
            @MinValue FLOAT,
            @MaxValue FLOAT,
            @CurrentValue FLOAT,
            @FirstValue FLOAT,
            @DataPoints INT,
            @Trend FLOAT,
            @ZScore FLOAT,
            @UpperBound FLOAT,
            @SuggestedGoal FLOAT;

    -- Table variable to store monthly targets
    DECLARE @MonthlyTargets TABLE (
        MonthNumber INT PRIMARY KEY, -- Added primary key for clarity
        TargetValue FLOAT
    );

    -- =========================================================================
    -- Data Validation (Basic)
    -- =========================================================================
    -- Ensure the metric exists to avoid division by zero or NULL issues later
    IF NOT EXISTS (SELECT 1 FROM HistoricalMetrics WHERE MetricName = @MetricName)
    BEGIN
        PRINT 'Error: No data found for the specified MetricName: ' + @MetricName;
        -- Optionally, return an error code or an empty result set
        RETURN -1; -- Indicate error
    END;

    -- =========================================================================
    -- Calculate Statistics from Historical Data
    -- =========================================================================

    -- Calculate Median using a common method compatible across SQL Server versions
    -- (PERCENTILE_CONT requires SQL Server 2012+)
    WITH MedianCTE AS (
        SELECT
            MetricValue,
            ROW_NUMBER() OVER (ORDER BY MetricValue ASC) AS RowAsc,
            ROW_NUMBER() OVER (ORDER BY MetricValue DESC) AS RowDesc
        FROM HistoricalMetrics
        WHERE MetricName = @MetricName
    )
    SELECT @Median = AVG(1.0 * MetricValue) -- Use 1.0 for implicit float conversion
    FROM MedianCTE
    WHERE RowAsc BETWEEN (RowDesc + 1.0) / 2.0 AND (RowAsc + 1.0) / 2.0; -- Corrected median logic slightly for clarity

    -- Fetch other basic statistics, first/last values in a single pass
    WITH MetricData AS (
        SELECT
            MetricValue,
            MetricDate,
            ROW_NUMBER() OVER (ORDER BY MetricDate ASC) as rn_asc,
            ROW_NUMBER() OVER (ORDER BY MetricDate DESC) as rn_desc
        FROM HistoricalMetrics
        WHERE MetricName = @MetricName
    ),
    StatsCalculation AS (
        SELECT
            AVG(CAST(MetricValue AS FLOAT)) AS CalculatedMean,
            STDEV(MetricValue) AS CalculatedStdDev,
            MIN(MetricValue) AS CalculatedMinValue,
            MAX(MetricValue) AS CalculatedMaxValue,
            COUNT(*) AS CalculatedDataPoints,
            -- Use conditional aggregation to get first/last values based on row number
            MAX(CASE WHEN rn_asc = 1 THEN MetricValue END) AS CalculatedFirstValue,
            MAX(CASE WHEN rn_desc = 1 THEN MetricValue END) AS CalculatedCurrentValue
        FROM MetricData
    )
    SELECT
        @Mean = CalculatedMean,
        @StdDev = ISNULL(CalculatedStdDev, 0), -- Handle potential NULL if only one data point
        @MinValue = CalculatedMinValue,
        @MaxValue = CalculatedMaxValue,
        @DataPoints = CalculatedDataPoints,
        @FirstValue = CalculatedFirstValue,
        @CurrentValue = CalculatedCurrentValue
    FROM StatsCalculation;

    -- Handle cases with insufficient data for trend calculation
    IF @DataPoints < 2 OR @FirstValue IS NULL OR @CurrentValue IS NULL
    BEGIN
        SET @Trend = 0; -- Cannot calculate trend with less than 2 points
    END
    ELSE
    BEGIN
        -- Calculate trend (simple linear change over the period)
        SET @Trend = (@CurrentValue - @FirstValue) / @DataPoints;
    END;

    -- =========================================================================
    -- Calculate Goal Metrics
    -- =========================================================================

    -- Determine the Z-Score based on the desired confidence level
    -- These are common Z-scores for one-tailed intervals.
    SET @ZScore = CASE
        WHEN @ConfidenceLevel >= 0.95 THEN 1.645 -- 95% Confidence
        WHEN @ConfidenceLevel >= 0.90 THEN 1.282 -- 90% Confidence
        WHEN @ConfidenceLevel >= 0.80 THEN 0.842 -- 80% Confidence
        WHEN @ConfidenceLevel >= 0.70 THEN 0.524 -- 70% Confidence
        ELSE 0.524 -- Default to 70% if input is invalid or lower
    END;

    -- Calculate the statistical upper bound based on historical performance
    SET @UpperBound = @Mean + (@ZScore * @StdDev);

    -- Calculate the suggested goal
    SET @SuggestedGoal = CASE
        -- Choose the lesser of the statistically derived upper bound or the historical max,
        -- both scaled by the improvement factor. This aims for a goal that is an
        -- improvement but grounded in historical performance and statistical likelihood.
        WHEN @UpperBound * @ImprovementFactor < @MaxValue * @ImprovementFactor
        THEN @UpperBound * @ImprovementFactor
        ELSE @MaxValue * @ImprovementFactor
    END;

    -- Ensure the suggested goal is at least the current value if aiming for improvement
    IF @SuggestedGoal < @CurrentValue AND @ImprovementFactor >= 1.0
    BEGIN
        SET @SuggestedGoal = @CurrentValue * @ImprovementFactor;
    END

    -- =========================================================================
    -- Calculate Monthly Targets (Linear Progression)
    -- =========================================================================
    DECLARE @MonthlyIncrement FLOAT;
    IF @CurrentValue IS NOT NULL AND @SuggestedGoal IS NOT NULL
    BEGIN
         -- Calculate the increment needed each month to reach the goal in 12 months
        SET @MonthlyIncrement = (@SuggestedGoal - @CurrentValue) / 12.0;
    END
    ELSE
    BEGIN
        SET @MonthlyIncrement = 0; -- Avoid errors if current value is null
    END

    DECLARE @Month INT = 1;
    DECLARE @TargetValue FLOAT;

    WHILE @Month <= 12
    BEGIN
        -- Calculate target for the current month
        SET @TargetValue = ISNULL(@CurrentValue, 0) + (@MonthlyIncrement * @Month);

        INSERT INTO @MonthlyTargets (MonthNumber, TargetValue)
        VALUES (@Month, @TargetValue);

        SET @Month = @Month + 1;
    END;

    -- =========================================================================
    -- Return Results
    -- =========================================================================

    -- Result Set 1: Baseline Metrics
    SELECT
        'Baseline Metrics' AS Category,
        ROUND(ISNULL(@Mean, 0), 2) AS Mean,
        ROUND(ISNULL(@Median, 0), 2) AS Median,
        ROUND(ISNULL(@StdDev, 0), 2) AS StandardDeviation,
        ROUND(ISNULL(@MinValue, 0), 2) AS MinimumValue,
        ROUND(ISNULL(@MaxValue, 0), 2) AS MaximumValue,
        ROUND(ISNULL(@Trend, 0), 4) AS CurrentTrendPerPeriod -- Increased precision for trend
    WHERE @DataPoints > 0; -- Only show baseline if data exists

    -- Result Set 2: Goal Metrics
    SELECT
        'Goal Metrics' AS Category,
        ROUND(ISNULL(@SuggestedGoal, 0), 2) AS SuggestedGoal,
        @ConfidenceLevel AS ConfidenceLevelUsed,
        @ImprovementFactor AS ImprovementFactorUsed
    WHERE @DataPoints > 0; -- Only show goal if data exists

    -- Result Set 3: Monthly Targets
    SELECT
        'Monthly Targets' AS Category,
        MonthNumber,
        ROUND(TargetValue, 2) AS TargetValue
    FROM @MonthlyTargets
    ORDER BY MonthNumber;

END;
GO
