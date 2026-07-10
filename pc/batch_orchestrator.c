/*
 * batch_orchestrator.c - Tuxedo Batch Processing Orchestrator
 *
 * Main driver that chains batch services in the correct order:
 *   BATCH_INGEST → BATCH_VALIDATE → BATCH_TRANSFORM → BATCH_REPORT
 *
 * In a real Tuxedo system, this would be the batch client that
 * calls services via tpcall(). The UBBCONFIG would define the
 * service topology and the Tuxedo bulletin board would handle
 * routing and load balancing.
 *
 * For this simulation, we use a service dispatch table and call
 * services directly — the tuxlib layer handles the TPSVCINFO
 * wrapping so the service code is identical to production.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include "atmi.h"
#include "userlog.h"
#include "sqlca.h"

/* ─── Forward declarations of service entry points ──────────────────────
 * These are the functions advertised in UBBCONFIG *SERVICES section.
 * Each matches the TPSVCINFO signature required by Tuxedo.
 */

extern void BATCH_INGEST(TPSVCINFO *rqst);
extern void BATCH_VALIDATE(TPSVCINFO *rqst);
extern void BATCH_TRANSFORM(TPSVCINFO *rqst);
extern void BATCH_REPORT(TPSVCINFO *rqst);

/* ─── Forward declarations of server init/done (renamed by preproc) ──── */

extern int  batch_ingest_svrinit(int argc, char *argv[]);
extern void batch_ingest_svrdone(void);
extern int  batch_validate_svrinit(int argc, char *argv[]);
extern void batch_validate_svrdone(void);
extern int  batch_transform_svrinit(int argc, char *argv[]);
extern void batch_transform_svrdone(void);
extern int  batch_report_svrinit(int argc, char *argv[]);
extern void batch_report_svrdone(void);

/* ─── Service Registration Table ────────────────────────────────────────
 * Equivalent to the *SERVICES section in UBBCONFIG:
 *
 *   BATCH_INGEST
 *   BATCH_VALIDATE
 *   BATCH_TRANSFORM
 *   BATCH_REPORT
 */

static SERVICE_TABLE service_table[] = {
    { "BATCH_INGEST",    BATCH_INGEST    },
    { "BATCH_VALIDATE",  BATCH_VALIDATE  },
    { "BATCH_TRANSFORM", BATCH_TRANSFORM },
    { "BATCH_REPORT",    BATCH_REPORT    },
    { NULL, NULL }
};

/* ─── Call a service by name ────────────────────────────────────────────
 * Wraps tpcall() for simple string-based request/response.
 */

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

    /* odata is now always a malloc'd copy from tpreturn */
    if (odata) free(odata);
    if (idata) free(idata);

    return rc;
}

/* ─── Initialize database schema ─────────────────────────────────────── */

static int init_database(void)
{
    sqlite3 *db = NULL;
    int rc = sqlite3_open("data/batch.db", &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n", sqlite3_errmsg(db));
        return -1;
    }

    /* Read and execute schema.sql */
    FILE *fp = fopen("sql/schema.sql", "r");
    if (!fp) {
        fprintf(stderr, "Cannot open sql/schema.sql\n");
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
    userlog("init_database: Schema initialized successfully");
    return 0;
}

/* ─── Load data from JSON file ───────────────────────────────────────── */

static char *load_input_data(const char *filepath, long *out_len)
{
    FILE *fp = fopen(filepath, "r");
    if (!fp) {
        userlog("load_input_data: Cannot open '%s'. Using demo data.", filepath);
        /* Generate demo data inline — realistic batch records */
        const char *demo =
            "1|1|sunt aut facere repellat provident occaecati excepturi optio|quia et suscipit suscipit recusandae consequuntur expedita et cum reprehenderit molestiae ut ut quas totam nostrum rerum est autem sunt rem eveniet architecto\n"
            "1|2|qui est esse rerum tempore vitae|est rerum tempore vitae sequi sint nihil reprehenderit dolor beatae ea dolores neque fugiat blanditiis voluptate porro vel nihil molestiae ut reiciendis qui aperiam non debitis possimus\n"
            "2|3|ea molestias quasi exercitationem repellat|et iusto sed quo iure voluptatem occaecati omnis eligendi aut ad voluptatem doloribus vel accusantium quis pariatur molestiae porro eius odio et labore et velit aut\n"
            "2|4|eum et est occaecati ullam saepe|ullam et saepe reiciendis voluptatem adipisci sit amet autem assumenda provident rerum culpa quis hic commodi nesciunt rem tenetur doloremque ipsam iure quis sunt voluptatem rerum\n"
            "3|5|nesciunt quas odio dolorem tempora|repudiandae veniam quaerat sunt sed alias aut fugiat sit autem sed est voluptatem omnis possimus esse voluptatibus quis est aut tenetur dolor neque dolorum\n"
            "3|6|dolorem eum magni eos aperiam quia|qui ratione voluptatem sequi nesciunt neque porro quisquam est qui dolorem ipsum quia dolor sit amet consectetur adipisci velit sed quia non numquam eius modi tempora\n"
            "4|7|magnam facilis autem voluptatem|dolore placeat quibusdam ea quo voluptas nulla veniam nisi odit ut quas qui voluptatem officiis harum nihil quis provident mollitia nobis aliquid\n"
            "4|8|dolorem dolore est ipsam aspernatur|ut aspernatur corporis harum nihil quis provident sequi mollitia nobis aliquid molestiae perspiciatis et ea nemo ab reprehenderit accusantium quas voluptate dolores\n"
            "5|9|nesciunt iure omnis dolorem|nam qui vel suscipit distinctio nihil minus explicabo ipsum consequatur non quasi voluptatem atque molestiae natus rerum excepturi deleniti voluptas\n"
            "5|10|optio molestias id quia eos|voluptatem animi nihil autem numquam et voluptatem nulla et autem sint dolorum sit ducimus autem reprehenderit perspiciatis error sit voluptatem accusantium doloremque\n";

        char *data = strdup(demo);
        *out_len = strlen(data);
        return data;
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

/* ─── main ───────────────────────────────────────────────────────────────
 *
 * Batch window execution flow:
 *
 *   1. Initialize database schema
 *   2. Call tpsvrinit() for each service (simulated in tuxlib)
 *   3. Load input data
 *   4. Execute batch pipeline:
 *      BATCH_INGEST → BATCH_VALIDATE → BATCH_TRANSFORM → BATCH_REPORT
 *   5. Print final report
 *   6. Call tpsvrdone() for each service
 *
 * In production Tuxedo, steps 3-5 would be triggered by a cron job
 * or an external scheduler. The services would already be running
 * (booted via tmboot) and the client would submit requests via tpcall.
 */

int main(int argc, char *argv[])
{
    char response[4096];
    char *input_data = NULL;
    long input_len = 0;

    printf("\n");
    printf("╔══════════════════════════════════════════════════╗\n");
    printf("║     TUXEDO BATCH PROCESSING SYSTEM              ║\n");
    printf("║     Pro*C + SQLite Simulation                   ║\n");
    printf("╚══════════════════════════════════════════════════╝\n\n");

    /* ── Step 0: Init ── */
    sqlca_init();
    tux_init(argc, argv);
    tux_run(service_table);

    if (init_database() != 0) {
        fprintf(stderr, "FATAL: Database initialization failed\n");
        return 1;
    }

    /* ── Boot services (simulates tmboot) ── */
    userlog("main: Booting services (tmboot simulation)...");
    batch_ingest_svrinit(argc, argv);
    batch_validate_svrinit(argc, argv);
    batch_transform_svrinit(argc, argv);
    batch_report_svrinit(argc, argv);
    userlog("main: All services booted");

    /* ── Step 1: Load data ── */
    const char *datafile = (argc > 1) ? argv[1] : "data/input.dat";
    input_data = load_input_data(datafile, &input_len);
    userlog("Input data: %ld bytes ready", input_len);

    /* ── Step 2: BATCH_INGEST ── */
    printf("\n─── Phase 1: BATCH_INGEST ───\n");
    if (call_service("BATCH_INGEST", input_data, response, sizeof(response)) == 0) {
        printf("  Result: %s\n", response);
    } else {
        printf("  FAILED: %s\n", response);
        goto cleanup;
    }

    /* ── Step 3: BATCH_VALIDATE ── */
    printf("\n─── Phase 2: BATCH_VALIDATE ───\n");
    if (call_service("BATCH_VALIDATE", "", response, sizeof(response)) == 0) {
        printf("  Result: %s\n", response);
    } else {
        printf("  FAILED: %s\n", response);
        goto cleanup;
    }

    /* ── Step 4: BATCH_TRANSFORM ──
     * Note: In UBBCONFIG, this service would tpforward to BATCH_REPORT.
     * So we don't call BATCH_REPORT separately — it's chained.
     */
    printf("\n─── Phase 3: BATCH_TRANSFORM ───\n");
    if (call_service("BATCH_TRANSFORM", "", response, sizeof(response)) == 0) {
        printf("  Result: %s\n", response);
    } else {
        printf("  FAILED: %s\n", response);
        goto cleanup;
    }

    /* ── Step 5: BATCH_REPORT ──
     * Already invoked via tpforward from BATCH_TRANSFORM.
     * Calling it again here would double-report.
     */
    printf("\n─── Phase 4: BATCH_REPORT ───\n");
    printf("  (delivered via tpforward chain — see above)\n");

    printf("\n╔══════════════════════════════════════════════════╗\n");
    printf("║     BATCH PROCESSING COMPLETE                   ║\n");
    printf("╚══════════════════════════════════════════════════╝\n");

cleanup:
    /* ── Shutdown services (simulates tmshutdown) ── */
    batch_report_svrdone();
    batch_transform_svrdone();
    batch_validate_svrdone();
    batch_ingest_svrdone();
    tux_done();
    free(input_data);
    return 0;
}
