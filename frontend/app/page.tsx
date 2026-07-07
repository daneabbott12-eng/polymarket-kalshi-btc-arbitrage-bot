"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { AlertCircle, TrendingUp } from "lucide-react"

interface MarketData {
  timestamp: string
  polymarket: {
    price_to_beat: number
    current_price: number
    prices: {
      Up: number
      Down: number
    }
    slug: string
  }
  kalshi: {
    event_ticker: string
    current_price: number
    markets: Array<{
      strike: number
      yes_ask: number
      no_ask: number
      subtitle: string
    }>
  }
  checks: Array<Check>
  opportunities: Array<Check>
  errors: string[]
  paper?: PaperSummary
}

interface Execution {
  target_size: number
  fill_size: number
  avg_poly_cost: number
  avg_kalshi_cost: number
  total_cost_at_size: number
  fee_per_contract: number
  net_margin_at_size: number
  slippage_per_leg: number
  total_slippage: number
  net_margin_slipped: number
  fill_probability: number
  risk_adj_net_margin: number
  total_net_pnl: number
  total_net_pnl_slipped: number
  risk_adj_net_pnl: number
  is_arbitrage_at_size: boolean
}

interface Check {
  kalshi_strike: number
  type: string
  poly_leg: string
  kalshi_leg: string
  poly_cost: number
  kalshi_cost: number
  total_cost: number
  poly_size: number
  kalshi_size: number
  max_size: number
  gross_margin: number
  fees: number
  net_margin: number
  is_arbitrage: boolean
  margin: number
  execution?: Execution | null
}

interface PaperSummary {
  total_trades: number
  open: number
  settled: number
  total_invested: number
  expected_net_pnl: number
  risk_adj_net_pnl: number
  realized_net_pnl: number
}

interface AutoStatus {
  mode: string
  armed: boolean
  arm_flag: boolean
  has_credentials: boolean
  max_order_contracts: number
  max_open_positions: number
  open_positions: number
}

interface PaperTrade {
  timestamp: string
  window: string
  kalshi_strike: number
  poly_leg: string
  kalshi_leg: string
  size: number
  cost_basis: number
  net_margin_per_contract: number
  expected_net_pnl: number
  risk_adj_net_per_contract: number
  risk_adj_net_pnl: number
  status: string
  realized_pnl: number | null
}

export default function Dashboard() {
  const [data, setData] = useState<MarketData | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())
  const [paperTrades, setPaperTrades] = useState<PaperTrade[]>([])
  const [autoStatus, setAutoStatus] = useState<AutoStatus | null>(null)

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

  const fetchData = async () => {
    try {
      const res = await fetch("/api/arbitrage")
      const json = await res.json()
      setData(json)
      setLastUpdated(new Date())
      setLoading(false)
    } catch (err) {
      console.error("Failed to fetch data", err)
      // On failure, we should probably set loading to false to show the dashboard
      // with whatever data we currently have, or an empty state
      setLoading(false)
    }
  }

  const fetchPaperTrades = async () => {
    try {
      const res = await fetch("/api/paper/trades")
      const json = await res.json()
      setPaperTrades(json.trades || [])
    } catch (err) {
      console.error("Failed to fetch paper trades", err)
    }
  }

  const fetchAutoStatus = async () => {
    try {
      const res = await fetch("/api/auto/status")
      setAutoStatus(await res.json())
    } catch (err) {
      console.error("Failed to fetch auto status", err)
    }
  }

  const simulatePaperTrade = async () => {
    await fetch("/api/paper/simulate", { method: "POST" })
    fetchPaperTrades()
  }

  const resetPaperTrades = async () => {
    await fetch("/api/paper/reset", { method: "POST" })
    fetchPaperTrades()
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Initial fetch
    fetchData()
    fetchPaperTrades()
    fetchAutoStatus()

    // Setup polling
    const interval = setInterval(() => {
      fetchData()
      fetchPaperTrades()
      fetchAutoStatus()
    }, 1000)

    return () => clearInterval(interval)
  }, [])

  if (loading) return <div className="flex items-center justify-center h-screen">Loading...</div>

  if (!data) return <div className="p-8">No data available</div>

  const bestOpp = data.opportunities.length > 0
    ? data.opportunities.reduce((prev, current) => (prev.margin > current.margin) ? prev : current)
    : null

  return (
    <div className="p-8 space-y-8 bg-slate-50 min-h-screen">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">Arbitrage Bot Dashboard</h1>
          <Badge variant="outline" className="animate-pulse bg-green-100 text-green-800 border-green-200">
            <span className="w-2 h-2 rounded-full bg-green-500 mr-2"></span>
            Live
          </Badge>
          {autoStatus && (
            <Badge
              variant="outline"
              className={autoStatus.mode === "LIVE"
                ? "bg-red-100 text-red-800 border-red-300"
                : "bg-slate-100 text-slate-600 border-slate-300"}
              title={`Auto-execution: ${autoStatus.mode}. Max ${autoStatus.max_order_contracts} contracts/order.`}
            >
              {autoStatus.mode === "LIVE" ? "⚠ LIVE TRADING" : "Auto: DRY-RUN"}
            </Badge>
          )}
        </div>
        <div className="text-sm text-muted-foreground">
          Last updated: {lastUpdated.toLocaleTimeString()}
        </div>
      </div>

      {data.errors.length > 0 && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md flex items-start gap-2">
          <AlertCircle className="h-5 w-5 mt-0.5" />
          <div>
            <strong className="font-bold block mb-1">Errors Detected:</strong>
            <ul className="list-disc ml-5 text-sm">
              {data.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Best Opportunity Hero Card */}
      {bestOpp && (
        <Card className="bg-gradient-to-r from-green-50 to-emerald-50 border-green-200 shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2 text-green-700">
              <TrendingUp className="h-5 w-5" />
              <CardTitle>Best Opportunity Found</CardTitle>
            </div>
            <CardDescription>Risk-free arbitrage detected with highest margin</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col md:flex-row justify-between items-center gap-4">
              <div className="text-center md:text-left">
                <div className="text-sm text-muted-foreground">Net Profit Margin</div>
                <div className="text-4xl font-bold text-green-700">${bestOpp.net_margin.toFixed(3)}</div>
                <div className="text-xs text-green-600 font-medium">per contract, after fees</div>
              </div>

              <div className="flex-1 bg-white p-4 rounded-lg border border-green-100 w-full">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-semibold text-slate-700">Strategy</span>
                  <Badge className="bg-green-600">Buy Both</Badge>
                </div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Polymarket {bestOpp.poly_leg}</span>
                  <span className="font-mono">${bestOpp.poly_cost.toFixed(3)}</span>
                </div>
                <div className="flex justify-between text-sm mb-3">
                  <span>Kalshi {bestOpp.kalshi_leg} (${bestOpp.kalshi_strike.toLocaleString()})</span>
                  <span className="font-mono">${bestOpp.kalshi_cost.toFixed(3)}</span>
                </div>
                <div className="pt-2 border-t border-dashed border-slate-200 flex justify-between font-bold">
                  <span>Total Cost</span>
                  <span>${bestOpp.total_cost.toFixed(3)}</span>
                </div>
                <div className="flex justify-between text-xs text-muted-foreground mt-2">
                  <span>Gross Margin</span>
                  <span className="font-mono">${bestOpp.gross_margin.toFixed(3)}</span>
                </div>
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Trading Fees</span>
                  <span className="font-mono text-red-500">−${bestOpp.fees.toFixed(3)}</span>
                </div>
                <div className="flex justify-between text-xs font-semibold text-green-700 pt-1 border-t border-dashed border-slate-200 mt-1">
                  <span>Net Margin</span>
                  <span className="font-mono">${bestOpp.net_margin.toFixed(3)}</span>
                </div>
                <div className="flex justify-between text-xs text-muted-foreground mt-2">
                  <span>Executable Depth</span>
                  <span className="font-mono">~{Math.floor(bestOpp.max_size).toLocaleString()} contracts</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Polymarket Card */}
        <Card>
          <CardHeader>
            <CardTitle>Polymarket</CardTitle>
            <CardDescription>Target: {data.polymarket?.slug || "Unavailable"}</CardDescription>
          </CardHeader>
          <CardContent>
            {data.polymarket ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-100 p-3 rounded-md">
                    <div className="text-xs text-muted-foreground uppercase font-bold">Price to Beat</div>
                    <div className="text-xl font-mono font-semibold">${data.polymarket.price_to_beat?.toLocaleString() || "N/A"}</div>
                  </div>
                  <div className="bg-slate-100 p-3 rounded-md">
                    <div className="text-xs text-muted-foreground uppercase font-bold">Current Price</div>
                    <div className="text-xl font-mono font-semibold">${data.polymarket.current_price?.toLocaleString() || "N/A"}</div>
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between items-center text-sm">
                    <span>UP Contract</span>
                    <span className="font-mono font-medium">${data.polymarket.prices?.Up?.toFixed(3) || "0.000"}</span>
                  </div>
                  <Progress value={(data.polymarket.prices?.Up || 0) * 100} className="h-2 bg-slate-100" indicatorClassName="bg-green-500" />

                  <div className="flex justify-between items-center text-sm mt-2">
                    <span>DOWN Contract</span>
                    <span className="font-mono font-medium">${data.polymarket.prices?.Down?.toFixed(3) || "0.000"}</span>
                  </div>
                  <Progress value={(data.polymarket.prices?.Down || 0) * 100} className="h-2 bg-slate-100" indicatorClassName="bg-red-500" />
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center p-8 text-muted-foreground bg-slate-50 rounded-md border border-dashed">
                Polymarket data is currently unavailable
              </div>
            )}
          </CardContent>
        </Card>

        {/* Kalshi Card */}
        <Card>
          <CardHeader>
            <CardTitle>Kalshi</CardTitle>
            <CardDescription>Ticker: {data.kalshi?.event_ticker || "Unavailable"}</CardDescription>
          </CardHeader>
          <CardContent>
            {data.kalshi ? (
              <div className="space-y-4">
                <div className="bg-slate-100 p-3 rounded-md mb-4">
                  <div className="text-xs text-muted-foreground uppercase font-bold">Current Price</div>
                  <div className="text-xl font-mono font-semibold">${data.kalshi.current_price?.toLocaleString() || "N/A"}</div>
                </div>

                <div className="space-y-3 max-h-[200px] overflow-y-auto pr-2">
                  {data.kalshi.markets
                    ?.filter(m => !data.polymarket || Math.abs(m.strike - (data.polymarket.price_to_beat || 0)) < 2500)
                    .map((m, i) => (
                      <div key={i} className="text-sm border-b pb-2 last:border-0">
                        <div className="flex justify-between font-medium mb-1">
                          <span>{m.subtitle}</span>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="flex justify-between text-xs text-muted-foreground">
                            <span>Yes: {m.yes_ask}¢</span>
                            <span>No: {m.no_ask}¢</span>
                          </div>
                          <div className="flex h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                            <div className="bg-green-500 h-full" style={{ width: `${m.yes_ask}%` }}></div>
                            <div className="bg-red-500 h-full" style={{ width: `${m.no_ask}%` }}></div>
                          </div>
                        </div>
                      </div>
                    ))}
                  {(!data.kalshi.markets || data.kalshi.markets.length === 0) && (
                    <div className="text-center text-sm text-muted-foreground p-2">No markets available</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center p-8 text-muted-foreground bg-slate-50 rounded-md border border-dashed">
                Kalshi data is currently unavailable
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Arbitrage Checks Table */}
      <Card>
        <CardHeader>
          <CardTitle>Arbitrage Analysis</CardTitle>
          <CardDescription>Real-time comparison of all potential strategies</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">Type</TableHead>
                <TableHead>Kalshi Strike</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Cost Analysis</TableHead>
                <TableHead className="text-right">Total Cost</TableHead>
                <TableHead className="text-right">Depth</TableHead>
                <TableHead className="text-right">Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.checks.map((check, i) => {
                // A row is a genuine opportunity only if the backend confirmed it
                // (both legs tradeable, enough depth, total < $1.00) -- NOT merely
                // total_cost < 1.00, which an empty/illiquid leg can fake.
                const isArb = check.is_arbitrage
                const percentCost = Math.min(check.total_cost * 100, 100)

                return (
                  <TableRow key={i} className={isArb ? "bg-green-50/50" : ""}>
                    <TableCell>
                      <Badge variant="outline" className="whitespace-nowrap">
                        {check.type.replace("Poly", "P").replace("Kalshi", "K")}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      ${check.kalshi_strike.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-xs">
                      <div className="flex flex-col">
                        <span>Buy P-{check.poly_leg}</span>
                        <span>Buy K-{check.kalshi_leg}</span>
                      </div>
                    </TableCell>
                    <TableCell className="w-[30%]">
                      <div className="space-y-1">
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>${check.poly_cost.toFixed(3)} + ${check.kalshi_cost.toFixed(3)} <span className="text-red-400">+ ${check.fees.toFixed(3)} fee</span></span>
                          <span>{Math.round(check.total_cost * 100)}%</span>
                        </div>
                        <Progress
                          value={percentCost}
                          className="h-2"
                          indicatorClassName={isArb ? "bg-green-500" : "bg-slate-400"}
                        />
                        {check.execution && (
                          <div className="text-[11px] mt-0.5 text-muted-foreground">
                            @ {Math.floor(check.execution.fill_size)} filled (VWAP ${check.execution.total_cost_at_size.toFixed(3)}):{" "}
                            <span className={check.execution.net_margin_slipped > 0 ? "text-green-600 font-medium" : "text-red-500"}>
                              {check.execution.net_margin_slipped > 0 ? "+" : ""}${check.execution.net_margin_slipped.toFixed(3)}/ct
                            </span>
                            <span className="text-slate-400"> after slip · risk-adj </span>
                            <span className={check.execution.risk_adj_net_margin > 0 ? "text-green-600" : "text-red-400"}>
                              {check.execution.risk_adj_net_margin > 0 ? "+" : ""}${check.execution.risk_adj_net_margin.toFixed(3)}
                            </span>
                          </div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-mono font-bold">
                      ${check.total_cost.toFixed(3)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs text-muted-foreground">
                      {Math.floor(check.max_size).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      {isArb ? (
                        <Badge className="bg-green-600 hover:bg-green-700 whitespace-nowrap">
                          +${check.margin.toFixed(3)}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Paper Trading */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-start gap-4 flex-wrap">
            <div>
              <CardTitle>Paper Trading</CardTitle>
              <CardDescription>
                Simulated fills — no real orders, no funds moved. Confirmed opportunities are auto-recorded; use Simulate to test.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <button
                onClick={simulatePaperTrade}
                className="text-xs px-3 py-1.5 rounded-md bg-slate-800 text-white hover:bg-slate-700"
              >
                Simulate Trade
              </button>
              <button
                onClick={resetPaperTrades}
                className="text-xs px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-100"
              >
                Reset
              </button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {data.paper && (
            <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-2">
              {[
                { label: "Trades", value: `${data.paper.total_trades}` },
                { label: "Open", value: `${data.paper.open}` },
                { label: "Settled", value: `${data.paper.settled}` },
                { label: "Invested", value: `$${data.paper.total_invested.toFixed(2)}` },
                { label: "P&L (after slip)", value: `$${data.paper.expected_net_pnl.toFixed(2)}`, signed: data.paper.expected_net_pnl },
                { label: "P&L (risk-adj)", value: `$${data.paper.risk_adj_net_pnl.toFixed(2)}`, signed: data.paper.risk_adj_net_pnl },
              ].map((s) => (
                <div key={s.label} className="bg-slate-100 p-3 rounded-md">
                  <div className="text-xs text-muted-foreground uppercase font-bold">{s.label}</div>
                  <div className={`text-xl font-mono font-semibold ${
                    s.signed === undefined ? "" : s.signed >= 0 ? "text-green-700" : "text-red-600"
                  }`}>{s.value}</div>
                </div>
              ))}
            </div>
          )}
          <div className="text-[11px] text-muted-foreground mb-4">
            Execution model: ${(0.005).toFixed(3)} slippage/leg, 90% both-legs fill probability, $0.05 leg-risk loss if a leg goes naked. “Risk-adj” is the probability-weighted expectation.
          </div>

          {paperTrades.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground p-4 border border-dashed rounded-md">
              No paper trades yet. Genuine opportunities are recorded automatically, or click “Simulate Trade” to test the ledger.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Strategy</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead className="text-right">Invested</TableHead>
                  <TableHead className="text-right">Net / ct</TableHead>
                  <TableHead className="text-right">P&L (slip)</TableHead>
                  <TableHead className="text-right">P&L (risk-adj)</TableHead>
                  <TableHead className="text-right">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paperTrades.slice().reverse().map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs">
                      P-{t.poly_leg} + K-{t.kalshi_leg} <span className="text-muted-foreground">(${t.kalshi_strike.toLocaleString()})</span>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{t.size}</TableCell>
                    <TableCell className="text-right font-mono text-xs">${t.cost_basis.toFixed(2)}</TableCell>
                    <TableCell className={`text-right font-mono text-xs ${t.net_margin_per_contract >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {t.net_margin_per_contract >= 0 ? "+" : "−"}${Math.abs(t.net_margin_per_contract).toFixed(3)}
                    </TableCell>
                    <TableCell className={`text-right font-mono text-xs font-semibold ${t.expected_net_pnl >= 0 ? "text-green-700" : "text-red-600"}`}>
                      {t.expected_net_pnl >= 0 ? "+" : "−"}${Math.abs(t.expected_net_pnl).toFixed(2)}
                    </TableCell>
                    <TableCell className={`text-right font-mono text-xs ${t.risk_adj_net_pnl >= 0 ? "text-slate-500" : "text-red-500"}`}>
                      {t.risk_adj_net_pnl >= 0 ? "+" : "−"}${Math.abs(t.risk_adj_net_pnl).toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge variant="outline" className={t.status === "settled" ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-amber-50 text-amber-700 border-amber-200"}>
                        {t.status}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
