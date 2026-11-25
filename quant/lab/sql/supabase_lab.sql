-- Tabelle del laboratorio paper trading (schema public, prefisso lab_, come finance_* del progetto)
create table if not exists lab_decisions(id text primary key, strategy text, version text, ts text, note text, targets_json text);
create table if not exists lab_fills(
  id bigserial primary key, ts text, strategy text, version text, key text, qty double precision, price double precision,
  fee double precision, slippage double precision, reason text, notional double precision default 0,
  unique(ts, strategy, version, key, reason));
create table if not exists lab_marks(
  ts text, strategy text, version text, equity double precision, cash double precision, gross_exposure double precision,
  positions_json text, primary key(ts, strategy, version));
create table if not exists lab_reviews(
  ts text, strategy text, version text, period_from text, period_to text, metrics_json text, lessons_text text, flag text,
  primary key(ts, strategy, version));
create table if not exists lab_positions(strategy text, version text, key text, qty double precision, avg_price double precision,
  primary key(strategy, version, key));
create table if not exists lab_cash(strategy text, version text, cash double precision, primary key(strategy, version));
create table if not exists lab_runs(strategy text, version text, last_ts text, primary key(strategy, version));
create index if not exists lab_decisions_s on lab_decisions(strategy, ts desc);
create index if not exists lab_marks_s on lab_marks(strategy, ts desc);
