# Useful SQLite queries

Run these against `data/mortis.db` using SQLite. All performance statistics should be read with their sample count (`n`); do not treat a small sample as evidence.

1. **Closed outcomes by exit reason**

   ```sql
   SELECT exit_reason, COUNT(*) AS n,
          ROUND(100.0 * SUM(pnl_usd > 0) / COUNT(*), 1) AS win_rate_pct,
          ROUND(AVG(r_multiple), 3) AS average_r
   FROM trades WHERE status = 'closed'
   GROUP BY exit_reason ORDER BY n DESC;
   ```

2. **Average R by UTC entry hour**

   ```sql
   SELECT strftime('%H', opened_at / 1000, 'unixepoch') AS utc_hour,
          COUNT(*) AS n, ROUND(AVG(r_multiple), 3) AS average_r
   FROM trades WHERE status = 'closed'
   GROUP BY utc_hour ORDER BY utc_hour;
   ```

3. **Trade counts and outcomes by recorded trend regime**

   ```sql
   SELECT episode.trend_bucket, COUNT(*) AS n,
          ROUND(AVG(episode.r_multiple), 3) AS average_r
   FROM memory_episodes AS episode
   WHERE episode.counterfactual = 0 AND episode.outcome != 'unresolved'
   GROUP BY episode.trend_bucket ORDER BY n DESC;
   ```

4. **Fees and gross versus net P&L**

   ```sql
   SELECT COUNT(*) AS n, ROUND(SUM(pnl_gross), 2) AS gross_usd,
          ROUND(SUM(fee_usd), 2) AS fees_usd, ROUND(SUM(pnl_usd), 2) AS net_usd
   FROM trades WHERE status = 'closed';
   ```

5. **MAE/MFE by exit reason**

   ```sql
   SELECT exit_reason, COUNT(*) AS n,
          ROUND(AVG(mae_r), 3) AS average_mae_r,
          ROUND(AVG(mfe_r), 3) AS average_mfe_r
   FROM trades WHERE status = 'closed' GROUP BY exit_reason;
   ```

6. **Executed versus counterfactual outcomes**

   ```sql
   SELECT CASE WHEN counterfactual = 1 THEN 'counterfactual' ELSE 'executed' END AS kind,
          outcome, COUNT(*) AS n, ROUND(AVG(r_multiple), 3) AS average_r
   FROM memory_episodes WHERE outcome != 'unresolved'
   GROUP BY kind, outcome ORDER BY kind, outcome;
   ```

7. **Unresolved samples with their recorded reason**

   ```sql
   SELECT decision_id, created_at_ms, unresolved_reason
   FROM training_samples WHERE outcome_resolved = 0
   ORDER BY created_at_ms;
   ```

8. **Average bars held by side**

   ```sql
   SELECT side, COUNT(*) AS n, ROUND(AVG(bars_held), 1) AS average_bars
   FROM trades WHERE status = 'closed' GROUP BY side;
   ```

9. **Paper P&L by UTC day**

   ```sql
   SELECT utc_date, pnl_usd
   FROM daily_pnl ORDER BY utc_date;
   ```

10. **Recent decisions where memory gated the candidate**

    ```sql
    SELECT created_at_ms, decision_id, direction, rejection_reason,
           json_extract(memory_json, '$.n') AS memory_n,
           json_extract(memory_json, '$.shrunk_win_rate') AS shrunk_win_rate
    FROM decisions WHERE rejection_reason = 'memory_veto'
    ORDER BY created_at_ms DESC LIMIT 50;
    ```
