import { NextRequest, NextResponse } from "next/server";
import prisma from "@/lib/prisma";
import {
  computeStats,
  toWeeklyReturns,
  toMonthlyReturns,
  rollingRV,
  periodToFromDate,
  type StatsResponse,
} from "@/lib/statsCompute";

// index_id constants (from indices table)
const INDEX_IDS: Record<string, number> = {
  "^NSEI":  1,
  "SENSEX": 46,
};
const INDIAVIX_ID = 38;

const DAILY_THRESHOLDS   = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0];
const WEEKLY_THRESHOLDS  = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0];
const MONTHLY_THRESHOLDS = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0];

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl;
  const symbol = searchParams.get("symbol") ?? "^NSEI";
  const period = searchParams.get("period") ?? "5y";

  const indexId = INDEX_IDS[symbol];
  if (!indexId) {
    return NextResponse.json({ error: `Unknown symbol: ${symbol}` }, { status: 400 });
  }

  const fromDate = periodToFromDate(period);

  // Fetch index daily prices
  const rows = await prisma.index_daily_prices.findMany({
    where: {
      index_id: indexId,
      date: { gte: fromDate },
      close_price: { not: null },
    },
    select: { date: true, close_price: true },
    orderBy: { date: "asc" },
  });

  if (rows.length < 5) {
    return NextResponse.json({ error: "Not enough data for the selected period" }, { status: 404 });
  }

  const dates   = rows.map((r) => r.date.toISOString().split("T")[0]);
  const closes  = rows.map((r) => r.close_price as number);

  // Daily returns (%)
  const dailyReturns = closes
    .slice(1)
    .map((c, i) => (c / closes[i] - 1) * 100);

  // Weekly / monthly
  const weeklyReturns  = toWeeklyReturns(dates, closes);
  const monthlyReturns = toMonthlyReturns(dates, closes);

  // Compute stats for each period type
  const daily   = computeStats(dailyReturns,   -4.0,  4.0,  0.25, DAILY_THRESHOLDS);
  const weekly  = computeStats(weeklyReturns,  -8.0,  8.0,  0.5,  WEEKLY_THRESHOLDS);
  const monthly = computeStats(monthlyReturns, -15.0, 15.0, 2.0,  MONTHLY_THRESHOLDS);

  // Rolling 21D realized vol series
  const rv21dSeries = rollingRV(closes);

  // India VIX (IV proxy) for the same date range
  const vixRows = await prisma.index_daily_prices.findMany({
    where: {
      index_id: INDIAVIX_ID,
      date: { gte: fromDate },
      close_price: { not: null },
    },
    select: { date: true, close_price: true },
    orderBy: { date: "asc" },
  });

  // Build a date→vix map for easy lookup
  const vixByDate = new Map<string, number>(
    vixRows.map((r) => [r.date.toISOString().split("T")[0], r.close_price as number])
  );

  // Merge RV + VIX into a single series aligned to the index dates
  const iv_rv_series = dates.map((d, i) => ({
    date:  d,
    rv21d: rv21dSeries[i] ?? null,
    vix:   vixByDate.get(d) ?? null,
  })).filter((p) => p.rv21d !== null || p.vix !== null);

  const response: StatsResponse = {
    period,
    date_from: dates[0],
    date_to:   dates[dates.length - 1],
    daily,
    weekly,
    monthly,
    iv_rv_series,
  };

  return NextResponse.json(response, {
    headers: {
      // Cache for 1 hour — data is only updated daily
      "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
