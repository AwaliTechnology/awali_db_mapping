CREATE PROCEDURE CalculateAchievableGoal
    @MetricName VARCHAR(50),
    @ConfidenceLevel FLOAT = 0.7,
    @ImprovementFactor FLOAT = 1.1
AS
BEGIN
    -- Declare variables for calculations
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

    -- Calculate Median separately using a compatible method
    WITH MedianCTE AS (
        SELECT MetricValue,
            ROW_NUMBER() OVER (ORDER BY MetricValue) AS RowAsc,
            ROW_NUMBER() OVER (ORDER BY MetricValue DESC) AS RowDesc
        FROM HistoricalMetrics
        WHERE MetricName = @MetricName
    )
    SELECT @Median = AVG(1.0 * MetricValue)
    FROM MedianCTE
    WHERE RowAsc IN ((RowAsc + RowDesc + 1)/2, (RowAsc + RowDesc + 2)/2);

    -- Calculate other basic statistics
    WITH Stats AS (
        SELECT 
            AVG(CAST(MetricValue AS FLOAT)) AS Mean,
            STDEV(MetricValue) AS StdDev,
            MIN(MetricValue) AS MinValue,
            MAX(MetricValue) AS MaxValue,
            COUNT(*) AS DataPoints
        FROM HistoricalMetrics
        WHERE MetricName = @MetricName
    )
    SELECT 
        @Mean = Mean,
        @StdDev = StdDev,
        @MinValue = MinValue,
        @MaxValue = MaxValue,
        @DataPoints = DataPoints
    FROM Stats;

    -- Get current and first values
    SELECT @CurrentValue = MetricValue
    FROM HistoricalMetrics 
    WHERE MetricName = @MetricName 
    AND MetricDate = (
        SELECT MAX(MetricDate) 
        FROM HistoricalMetrics 
        WHERE MetricName = @MetricName
    );

    SELECT @FirstValue = MetricValue
    FROM HistoricalMetrics 
    WHERE MetricName = @MetricName 
    AND MetricDate = (
        SELECT MIN(MetricDate) 
        FROM HistoricalMetrics 
        WHERE MetricName = @MetricName
    );

    -- Calculate trend (simple linear)
    SET @Trend = (@CurrentValue - @FirstValue) / @DataPoints;

    -- Calculate Z-Score based on confidence level
    SET @ZScore = CASE 
        WHEN @ConfidenceLevel = 0.7 THEN 0.524
        WHEN @ConfidenceLevel = 0.8 THEN 0.842
        WHEN @ConfidenceLevel = 0.9 THEN 1.282
        WHEN @ConfidenceLevel = 0.95 THEN 1.645
        ELSE 0.524 -- Default to 70%
    END;

    -- Calculate upper bound and suggested goal
    SET @UpperBound = @Mean + (@ZScore * @StdDev);
    SET @SuggestedGoal = CASE 
        WHEN @UpperBound * @ImprovementFactor < @MaxValue * @ImprovementFactor
        THEN @UpperBound * @ImprovementFactor
        ELSE @MaxValue * @ImprovementFactor
    END;

    -- Create table for monthly targets
    DECLARE @MonthlyTargets TABLE (
        MonthNumber INT,
        TargetValue FLOAT
    );

    -- Calculate monthly targets
    DECLARE @MonthlyIncrement FLOAT = (@SuggestedGoal - @CurrentValue) / 12.0;
    DECLARE @Month INT = 1;

    WHILE @Month <= 12
    BEGIN
        INSERT INTO @MonthlyTargets (MonthNumber, TargetValue)
        VALUES (@Month, @CurrentValue + (@MonthlyIncrement * @Month));
        SET @Month = @Month + 1;
    END;

    -- Return results
    SELECT 
        'Baseline Metrics' AS Category,
        ROUND(@Mean, 2) AS Mean,
        ROUND(@Median, 2) AS Median,
        ROUND(@StdDev, 2) AS StandardDeviation,
        ROUND(@MinValue, 2) AS MinimumValue,
        ROUND(@MaxValue, 2) AS MaximumValue,
        ROUND(@Trend, 2) AS CurrentTrend;

    SELECT 
        'Goal Metrics' AS Category,
        ROUND(@SuggestedGoal, 2) AS SuggestedGoal,
        @ConfidenceLevel AS ConfidenceLevel,
        @ImprovementFactor AS ImprovementFactor;

    SELECT 
        'Monthly Targets' AS Category,
        MonthNumber,
        ROUND(TargetValue, 2) AS TargetValue
    FROM @MonthlyTargets
    ORDER BY MonthNumber;
END;
GO