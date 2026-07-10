/*
 * batch_equity_orchestrator.c - Tuxedo Equity Batch Orchestrator
 *
 * Main driver that chains equity batch services:
 *   BATCH_EQUITY_INGEST → BATCH_EQUITY_VALIDATE → BATCH_EQUITY_TRANSFORM
 *   → BATCH_EQUITY_REPORT (via tpforward from TRANSFORM)
 *
 * Also supports: BATCH_PORTFOLIO_PROCESSOR and BATCH_MARKET_ANALYTICS
 * as standalone services that can be invoked separately.
 *
 * For the ICICI Securities demo, this simulates:
 * - tmboot (service boot via tpsvrinit)
 * - tpcall (service dispatch)
 * - tmshutdown (service shutdown via tpsvrdone)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include "atmi.h"
#include "userlog.h"
#include "sqlca.h"

/* ─── Forward declarations of equity service entry points ──────────── */

extern void BATCH_EQUITY_INGEST(TPSVCINFO *rqst);
extern void BATCH_EQUITY_VALIDATE(TPSVCINFO *rqst);
extern void BATCH_EQUITY_TRANSFORM(TPSVCINFO *rqst);
extern void BATCH_EQUITY_REPORT(TPSVCINFO *rqst);
extern void BATCH_PORTFOLIO_PROCESSOR(TPSVCINFO *rqst);
extern void BATCH_MARKET_ANALYTICS(TPSVCINFO *rqst);
extern void BATCH_COMPREHENSIVE_RISK(TPSVCINFO *rqst);

/* ─── Forward declarations of server init/done ────────────────────── */

extern int  batch_equity_ingest_svrinit(int argc, char *argv[]);
extern void batch_equity_ingest_svrdone(void);
extern int  batch_equity_validate_svrinit(int argc, char *argv[]);
extern void batch_equity_validate_svrdone(void);
extern int  batch_equity_transform_svrinit(int argc, char *argv[]);
extern void batch_equity_transform_svrdone(void);
extern int  batch_equity_report_svrinit(int argc, char *argv[]);
extern void batch_equity_report_svrdone(void);
extern int  batch_portfolio_processor_svrinit(int argc, char *argv[]);
extern void batch_portfolio_processor_svrdone(void);
extern int  batch_market_analytics_svrinit(int argc, char *argv[]);
extern void batch_market_analytics_svrdone(void);
extern int  batch_comprehensive_risk_svrinit(int argc, char *argv[]);
extern void batch_comprehensive_risk_svrdone(void);

/* ─── Service Registration Table ────────────────────────────────────── */

static SERVICE_TABLE service_table[] = {
    { "BATCH_EQUITY_INGEST",      BATCH_EQUITY_INGEST      },
    { "BATCH_EQUITY_VALIDATE",    BATCH_EQUITY_VALIDATE    },
    { "BATCH_EQUITY_TRANSFORM",   BATCH_EQUITY_TRANSFORM   },
    { "BATCH_EQUITY_REPORT",      BATCH_EQUITY_REPORT      },
    { "BATCH_PORTFOLIO_PROCESSOR", BATCH_PORTFOLIO_PROCESSOR },
    { "BATCH_MARKET_ANALYTICS",   BATCH_MARKET_ANALYTICS   },
    { "BATCH_COMPREHENSIVE_RISK", BATCH_COMPREHENSIVE_RISK },
    { NULL, NULL }
};

/* ─── Call a service by name ──────────────────────────────────────── */

static int call_service(const char *svcname, const char *input,
                        char *output, int output_size)
{
    long  olen = 0;
    char *odata = NULL;
    char *idata = input ? strdup(input) : NULL;
    long  ilen = input ? strlen(input) + 1 : 0;

    int rc = tpcall(svcname, idata, ilen, &odata, &olen, 0);

    if (rc == 0 && odata && olen > 0 && output) {
        strncpy(output, odata, output_size - 1);
        output[output_size - 1] = '\0';
    }

    if (odata) free(odata);
    if (idata) free(idata);

    return rc;
}

/* ─── Initialize database schema ─────────────────────────────────── */

static int init_database(const char *schema_file)
{
    sqlite3 *db = NULL;
    int rc = sqlite3_open("data/batch.db", &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n", sqlite3_errmsg(db));
        return -1;
    }

    FILE *fp = fopen(schema_file, "r");
    if (!fp) {
        fprintf(stderr, "Cannot open %s\n", schema_file);
        sqlite3_close(db);
        return -1;
    }

    fseek(fp, 0, SEEK_END);
    long fsize = ftell(fp);
    fseek(fp, 0, SEEK_SET);

    char *sql = malloc(fsize + 1);
    fread(sql, 1, fsize, fp);
    sql[fsize] = '\0';
    fclose(fp);

    char *err = NULL;
    rc = sqlite3_exec(db, sql, NULL, NULL, &err);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Schema error: %s\n", err);
        sqlite3_free(err);
        free(sql);
        sqlite3_close(db);
        return -1;
    }

    free(sql);
    sqlite3_close(db);
    userlog("init_database: Schema initialized from %s", schema_file);
    return 0;
}

/* ─── Load input data file ───────────────────────────────────────── */

static char *load_input_data(const char *filepath, long *out_len)
{
    FILE *fp = fopen(filepath, "r");
    if (!fp) {
        userlog("load_input_data: Cannot open '%s'", filepath);
        return NULL;
    }

    fseek(fp, 0, SEEK_END);
    *out_len = ftell(fp);
    fseek(fp, 0, SEEK_SET);

    char *data = malloc(*out_len + 1);
    fread(data, 1, *out_len, fp);
    data[*out_len] = '\0';
    fclose(fp);

    userlog("load_input_data: Loaded %ld bytes from %s", *out_len, filepath);
    return data;
}

/* ─── Print usage ────────────────────────────────────────────────── */

static void print_usage(const char *prog)
{
    printf("Usage: %s [OPTIONS]\n\n", prog);
    printf("Options:\n");
    printf("  --pipeline       Run the full equity batch pipeline (default)\n");
    printf("  --portfolio      Run portfolio processor only\n");
    printf("  --analytics      Run market analytics only\n");
    printf("  --risk           Run comprehensive risk assessment\n");
    printf("  --all            Run all services sequentially\n");
    printf("  --input FILE     Input data file (default: data/eod_input.dat)\n");
    printf("  --schema FILE    Schema file (default: sql/schema_equity.sql)\n");
    printf("  --help           This message\n");
}

/* ─── main ─────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    char response[16384];
    char *input_data = NULL;
    long input_len = 0;
    const char *mode = "pipeline";
    const char *input_file = "data/eod_input.dat";
    const char *schema_file = "sql/schema_equity.sql";

    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--pipeline") == 0) mode = "pipeline";
        else if (strcmp(argv[i], "--portfolio") == 0) mode = "portfolio";
        else if (strcmp(argv[i], "--analytics") == 0) mode = "analytics";
        else if (strcmp(argv[i], "--risk") == 0) mode = "risk";
        else if (strcmp(argv[i], "--all") == 0) mode = "all";
        else if (strcmp(argv[i], "--input") == 0 && i + 1 < argc) input_file = argv[++i];
        else if (strcmp(argv[i], "--schema") == 0 && i + 1 < argc) schema_file = argv[++i];
        else if (strcmp(argv[i], "--help") == 0) { print_usage(argv[0]); return 0; }
    }

    printf("\n");
    printf("╔══════════════════════════════════════════════════════════╗\n");
    printf("║  ICICI SECURITIES — TUXEDO BATCH PROCESSING            ║\n");
    printf("║  NSE Equity Data Pipeline (Pro*C + Turso/SQLite)      ║\n");
    printf("╚══════════════════════════════════════════════════════════╝\n\n");

    /* ── Init ── */
    sqlca_init();
    tux_init(argc, argv);
    tux_run(service_table);

    if (init_database(schema_file) != 0) {
        fprintf(stderr, "FATAL: Database initialization failed\n");
        return 1;
    }

    /* ── Boot all services (tmboot simulation) ── */
    userlog("main: Booting services...");
    batch_equity_ingest_svrinit(argc, argv);
    batch_equity_validate_svrinit(argc, argv);
    batch_equity_transform_svrinit(argc, argv);
    batch_equity_report_svrinit(argc, argv);
    batch_portfolio_processor_svrinit(argc, argv);
    batch_market_analytics_svrinit(argc, argv);
    batch_comprehensive_risk_svrinit(argc, argv);
    userlog("main: All services booted");

    /* ── Load input data ── */
    input_data = load_input_data(input_file, &input_len);

    if (strcmp(mode, "pipeline") == 0 || strcmp(mode, "all") == 0) {
        /* ── Phase 1: INGEST ── */
        printf("\n─── Phase 1: BATCH_EQUITY_INGEST ───\n");
        if (input_data) {
            if (call_service("BATCH_EQUITY_INGEST", input_data, response, sizeof(response)) == 0) {
                printf("  Result: %s\n", response);
            } else {
                printf("  FAILED: %s\n", response);
                goto cleanup;
            }
        } else {
            printf("  SKIPPED: No input data file found\n");
        }

        /* ── Phase 2: VALIDATE ── */
        printf("\n─── Phase 2: BATCH_EQUITY_VALIDATE ───\n");
        if (call_service("BATCH_EQUITY_VALIDATE", "", response, sizeof(response)) == 0) {
            printf("  Result: %s\n", response);
        } else {
            printf("  FAILED: %s\n", response);
            goto cleanup;
        }

        /* ── Phase 3: TRANSFORM (chains to REPORT via tpforward) ── */
        printf("\n─── Phase 3: BATCH_EQUITY_TRANSFORM ───\n");
        if (call_service("BATCH_EQUITY_TRANSFORM", "", response, sizeof(response)) == 0) {
            printf("  Result: %s\n", response);
        } else {
            printf("  FAILED: %s\n", response);
            goto cleanup;
        }

        /* Phase 4: REPORT delivered via tpforward chain */
        printf("\n─── Phase 4: BATCH_EQUITY_REPORT ───\n");
        printf("  (delivered via tpforward chain from TRANSFORM)\n");
    }

    if (strcmp(mode, "portfolio") == 0 || strcmp(mode, "all") == 0) {
        printf("\n─── BATCH_PORTFOLIO_PROCESSOR ───\n");
        if (call_service("BATCH_PORTFOLIO_PROCESSOR", "", response, sizeof(response)) == 0) {
            printf("%s\n", response);
        } else {
            printf("  FAILED: %s\n", response);
        }
    }

    if (strcmp(mode, "analytics") == 0 || strcmp(mode, "all") == 0) {
        printf("\n─── BATCH_MARKET_ANALYTICS ───\n");
        if (call_service("BATCH_MARKET_ANALYTICS", "", response, sizeof(response)) == 0) {
            printf("%s\n", response);
        } else {
            printf("  FAILED: %s\n", response);
        }
    }

    if (strcmp(mode, "risk") == 0 || strcmp(mode, "all") == 0) {
        printf("\n─── BATCH_COMPREHENSIVE_RISK ───\n");

        /* Build FML input buffer */
        FML_BUF *risk_input = Falloc();
        if (risk_input) {
            char client[] = "ICI001234";
            char date[]   = "2026-07-07";
            int  flags    = SF_DEFAULT;
            char segment[] = "EQUITY";
            char pf_type[] = "DELIVERY";
            char req_id[]  = "REQ-RISK-20260707-001";

            Fadd(risk_input, FLD_CLIENT_CODE,    client,  strlen(client));
            Fadd(risk_input, FLD_RISK_DATE,      date,    strlen(date));
            Fadd(risk_input, FLD_SCENARIO_FLAG,  &flags,  sizeof(int));
            Fadd(risk_input, FLD_CLIENT_SEGMENT, segment, strlen(segment));
            Fadd(risk_input, FLD_PORTFOLIO_TYPE, pf_type, strlen(pf_type));
            Fadd(risk_input, FLD_REQUEST_ID,     req_id,  strlen(req_id));

            userlog("main: FML input buffer ready — %d fields", risk_input->field_count);

            long  olen = 0;
            char *odata = NULL;
            int rc = tpcall("BATCH_COMPREHENSIVE_RISK", (char *)risk_input,
                            sizeof(FML_BUF), &odata, &olen, 0);

            if (rc == 0) {
                FML_BUF *outbuf = (FML_BUF *)odata;
                if (outbuf && outbuf->buftype == FML) {
                    printf("  Risk Assessment Complete:\n");
                    printf("  ─────────────────────────\n");

                    double val;
                    char   str[512];
                    int    slen;

                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_VAR_95, 0, &val, &slen) == 0)
                        printf("  VaR 95%%:           ₹%.2f\n", val);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_VAR_99, 0, &val, &slen) == 0)
                        printf("  VaR 99%%:           ₹%.2f\n", val);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_SHARPE_RATIO, 0, &val, &slen) == 0)
                        printf("  Sharpe Ratio:       %.3f\n", val);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_MAX_DRAWDOWN, 0, &val, &slen) == 0)
                        printf("  Max Drawdown:       %.2f%%\n", val * 100.0);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_BETA_WEIGHTED, 0, &val, &slen) == 0)
                        printf("  Weighted Beta:      %.3f\n", val);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_STRESS_LOSS_PCT, 0, &val, &slen) == 0)
                        printf("  Stress Loss (S1):   %.2f%%\n", val * 100.0);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_CONCENTRATION_RISK, 0, &val, &slen) == 0)
                        printf("  Concentration Risk: %.1f/100\n", val);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_LIQUIDITY_SCORE, 0, &val, &slen) == 0)
                        printf("  Liquidity Score:    %.1f/100\n", val);
                    slen = sizeof(str);
                    if (Fget(outbuf, FLD_RISK_GRADE, 0, str, &slen) == 0)
                        printf("  Risk Grade:         %s\n", str);
                    slen = sizeof(str);
                    if (Fget(outbuf, FLD_ACTION_REQUIRED, 0, str, &slen) == 0)
                        printf("  Action Required:    %s\n", str);
                    slen = sizeof(double);
                    if (Fget(outbuf, FLD_MARGIN_DEFICIT, 0, &val, &slen) == 0)
                        printf("  Margin Deficit:    ₹%.2f\n", val);

                    /* Free FML output buffer */
                    if (outbuf) Ffree(outbuf);
                } else {
                    printf("  Result: %s\n", odata ? odata : "(no output)");
                    free(odata);
                }
            } else {
                printf("  FAILED (rc=%d)\n", rc);
                free(odata);
            }

            /* Free FML input buffer (tpcall copies, so safe to free) */
            Ffree(risk_input);
        }
    }

    printf("\n╔══════════════════════════════════════════════════════════╗\n");
    printf("║     BATCH PROCESSING COMPLETE                           ║\n");
    printf("╚══════════════════════════════════════════════════════════╝\n");

cleanup:
    /* ── Shutdown services (reverse order, tmshutdown simulation) ── */
    batch_comprehensive_risk_svrdone();
    batch_market_analytics_svrdone();
    batch_portfolio_processor_svrdone();
    batch_equity_report_svrdone();
    batch_equity_transform_svrdone();
    batch_equity_validate_svrdone();
    batch_equity_ingest_svrdone();
    tux_done();
    free(input_data);
    return 0;
}
