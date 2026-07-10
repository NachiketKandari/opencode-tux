/*
 * tuxlib.c - Simulated Tuxedo ATMI library
 *
 * Provides the runtime for service dispatch, tpalloc, tpfree,
 * and inter-service calls. Backed by an in-memory service registry.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdarg.h>
#include <time.h>
#include "atmi.h"

/* --- globals --- */
int tperrno = 0;
static SERVICE_TABLE *svc_registry = NULL;
static char *tpreturn_data = NULL;
static long tpreturn_len = 0;
static int tpreturn_rval = TPSUCCESS;

/* --- tpstrerror --- */
char *tpstrerror(int err)
{
    static char buf[64];
    snprintf(buf, sizeof(buf), "tperrno=%d", err);
    return buf;
}

/* --- userlog --- */
void userlog(const char *fmt, ...)
{
    va_list args;
    time_t now = time(NULL);
    char timestr[32];

    strftime(timestr, sizeof(timestr), "%Y-%m-%d %H:%M:%S", localtime(&now));
    fprintf(stderr, "[%s] ", timestr);

    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);

    fprintf(stderr, "\n");
    fflush(stderr);
}

/* ─── FML Implementation ──────────────────────────────────────────────── */

static int fldid_type_lookup(int fldid)
{
    switch (fldid) {
        case 100: case 101: case 103: case 104: case 105:  /* input strings */
        case 211: case 212: case 215:                       /* output strings */
            return FLD_STRING;
        case 102:                                            /* scenario flag */
            return FLD_INT;
        /* output doubles */
        case 200: case 201: case 202: case 203: case 204:
        case 205: case 206: case 207: case 208: case 209:
        case 210: case 213: case 214:
            return FLD_DOUBLE;
        default: return FLD_STRING;
    }
}

FML_BUF *Falloc(void)
{
    FML_BUF *fbfr = (FML_BUF *)calloc(1, sizeof(FML_BUF));
    if (fbfr) fbfr->buftype = FML;
    return fbfr;
}

void Ffree(FML_BUF *fbfr)
{
    free(fbfr);
}

int Fadd(FML_BUF *fbfr, int fldid, const void *value, int len)
{
    if (!fbfr || fbfr->field_count >= FML_MAX_FIELDS) return -1;

    FML_FIELD *f = &fbfr->fields[fbfr->field_count];
    f->fldid = fldid;
    f->type  = fldid_type_lookup(fldid);
    f->occ   = Fldno(fbfr, fldid);

    switch (f->type) {
        case FLD_STRING:
            if (value && len > 0) {
                int cp = len < 511 ? len : 511;
                memcpy(f->str_val, value, cp);
                f->str_val[cp] = '\0';
            }
            break;
        case FLD_INT:
            f->int_val = value ? *(int *)value : 0;
            break;
        case FLD_DOUBLE:
            f->dbl_val = value ? *(double *)value : 0.0;
            break;
    }
    fbfr->field_count++;
    return 0;
}

int Fget(FML_BUF *fbfr, int fldid, int occ, void *value, int *len)
{
    if (!fbfr) return -1;

    int found = 0;
    for (int i = 0; i < fbfr->field_count; i++) {
        FML_FIELD *f = &fbfr->fields[i];
        if (f->fldid == fldid) {
            if (found == occ) {
                switch (f->type) {
                    case FLD_STRING:
                        if (value && len) {
                            int cp = *len < 511 ? *len : 511;
                            memcpy(value, f->str_val, cp);
                            ((char *)value)[cp] = '\0';
                            *len = (int)strlen(f->str_val);
                        }
                        break;
                    case FLD_INT:
                        if (value) *(int *)value = f->int_val;
                        if (len) *len = sizeof(int);
                        break;
                    case FLD_DOUBLE:
                        if (value) *(double *)value = f->dbl_val;
                        if (len) *len = sizeof(double);
                        break;
                }
                return 0;
            }
            found++;
        }
    }
    return -1;
}

int Fchg(FML_BUF *fbfr, int fldid, int occ, const void *value, int len)
{
    if (!fbfr) return -1;

    int found = 0;
    for (int i = 0; i < fbfr->field_count; i++) {
        FML_FIELD *f = &fbfr->fields[i];
        if (f->fldid == fldid) {
            if (found == occ) {
                switch (f->type) {
                    case FLD_STRING:
                        if (value) {
                            int cp = len < 511 ? len : 511;
                            memcpy(f->str_val, value, cp);
                            f->str_val[cp] = '\0';
                        }
                        break;
                    case FLD_INT:
                        if (value) f->int_val = *(int *)value;
                        break;
                    case FLD_DOUBLE:
                        if (value) f->dbl_val = *(double *)value;
                        break;
                }
                return 0;
            }
            found++;
        }
    }
    return -1;
}

int Fldid(const char *fldname)
{
    if (!fldname) return -1;

    struct { const char *name; int id; } table[] = {
        {"CLIENT_CODE", 100}, {"RISK_DATE", 101}, {"SCENARIO_FLAG", 102},
        {"CLIENT_SEGMENT", 103}, {"PORTFOLIO_TYPE", 104}, {"REQUEST_ID", 105},
        {"VAR_95", 200}, {"VAR_99", 201}, {"MAX_DRAWDOWN", 202},
        {"SHARPE_RATIO", 203}, {"BETA_WEIGHTED", 204}, {"STRESS_LOSS_PCT", 205},
        {"STRESS_LOSS_PCT_2", 206}, {"STRESS_LOSS_PCT_3", 207},
        {"MARGIN_DEFICIT", 208}, {"CONCENTRATION_RISK", 209},
        {"LIQUIDITY_SCORE", 210}, {"RISK_GRADE", 211},
        {"ACTION_REQUIRED", 212}, {"TOTAL_EXPOSURE", 213},
        {"HEDGE_EFFECTIVENESS", 214}, {"SECTOR_EXPOSURE_JSON", 215},
        {NULL, -1}
    };
    for (int i = 0; table[i].name; i++) {
        if (strcasecmp(fldname, table[i].name) == 0) return table[i].id;
    }
    return -1;
}

int Fldno(FML_BUF *fbfr, int fldid)
{
    if (!fbfr) return 0;
    int count = 0;
    for (int i = 0; i < fbfr->field_count; i++) {
        if (fbfr->fields[i].fldid == fldid) count++;
    }
    return count;
}

/* ─── tpalloc ─────────────────────────────────────────────────────────── */

char *tpalloc(int buftype, char *subtype, long size)
{
    (void)subtype;
    if (buftype == FML) {
        FML_BUF *fb = Falloc();
        return (char *)fb;
    }
    return (char *)calloc(1, (size_t)size);
}

/* ─── tpfree ──────────────────────────────────────────────────────────── */

void tpfree(char *ptr)
{
    if (!ptr) return;
    /* If ptr looks like an FML buffer, use Ffree */
    FML_BUF *fb = (FML_BUF *)ptr;
    if (fb->buftype == FML) {
        Ffree(fb);
        return;
    }
    free(ptr);
}

/* --- Service lookup --- */
static TPSVCFUNC find_service(const char *svcname)
{
    if (!svc_registry) return NULL;
    for (int i = 0; svc_registry[i].svcname != NULL; i++) {
        if (strcmp(svc_registry[i].svcname, svcname) == 0) {
            return svc_registry[i].func;
        }
    }
    return NULL;
}

/* --- tux_init --- */
int tux_init(int argc, char *argv[])
{
    userlog("tux_init: Tuxedo simulation library initialized");
    return 0;
}

void tux_done(void)
{
    userlog("tux_done: Tuxedo simulation library shutdown");
}

/* --- tux_run: calls each service's tpsvrinit, then dispatches --- */
int tux_run(SERVICE_TABLE *svctab)
{
    svc_registry = svctab;
    userlog("tux_run: Service registry loaded with %d entries",
            (int)(sizeof(svc_registry) / sizeof(svc_registry[0])));

    /* Call tpsvrinit for each server via an indirect mechanism.
     * In this simulation, services are called directly by the orchestrator. */
    return 0;
}

/* --- tpcall: synchronous service call --- */
int tpcall(const char *svcname, char *idata, long ilen, char **odata, long *olen, long flags)
{
    TPSVCFUNC func = find_service(svcname);
    if (!func) {
        userlog("tpcall: service '%s' not found", svcname);
        tperrno = 6; /* TPENOENT */
        return -1;
    }

    userlog("tpcall: calling service '%s'", svcname);

    TPSVCINFO rqst;
    memset(&rqst, 0, sizeof(rqst));
    strncpy(rqst.name, svcname, sizeof(rqst.name) - 1);
    rqst.flags = flags;
    rqst.data = idata;
    rqst.len = ilen;

    func(&rqst);

    /* Pick up data set by tpreturn and transfer ownership */
    if (odata) *odata = tpreturn_data;
    if (olen)  *olen  = tpreturn_len;
    tpreturn_data = NULL;
    tpreturn_len = 0;

    /* Propagate service failure to caller */
    if (tpreturn_rval != TPSUCCESS) {
        tpreturn_rval = TPSUCCESS;  /* reset for next call */
        return -1;
    }
    return 0;
}

/* --- tpacall: asynchronous service call --- */
int tpacall(const char *svcname, char *data, long len, long flags)
{
    userlog("tpacall: async call to '%s' (deferred)", svcname);
    (void)data; (void)len; (void)flags;
    return 0;
}

int tpgetrply(int *cd, char **data, long *len, long flags)
{
    (void)cd; (void)data; (void)len; (void)flags;
    return 0;
}

/* --- tpreturn --- */
void tpreturn(int rval, long rcode, char *data, long len, long flags)
{
    userlog("tpreturn: rval=%d rcode=%ld len=%ld", rval, rcode, len);
    (void)flags;

    /* Free previous return data */
    free(tpreturn_data);
    tpreturn_data = NULL;
    tpreturn_len = 0;

    /* Copy the return data for tpcall to pick up */
    if (data && len > 0) {
        tpreturn_data = malloc((size_t)len);
        if (tpreturn_data) {
            memcpy(tpreturn_data, data, (size_t)len);
            tpreturn_len = len;
        }
    }

    tpreturn_rval = rval;
    if (rval != TPSUCCESS) {
        tperrno = 5;  /* TPESVCFAIL */
    }
}

/* --- tpforward --- */
void tpforward(const char *svcname, char *data, long len, long flags)
{
    userlog("tpforward: forwarding to '%s'", svcname);
    TPSVCFUNC func = find_service(svcname);
    if (func) {
        TPSVCINFO rqst;
        memset(&rqst, 0, sizeof(rqst));
        strncpy(rqst.name, svcname, sizeof(rqst.name) - 1);
        rqst.flags = flags;
        rqst.data = data;
        rqst.len = len;
        func(&rqst);
    } else {
        userlog("tpforward: service '%s' not found", svcname);
    }
}

/* --- Transaction stubs --- */
int tpbegin(unsigned long timeout, long flags)
{
    userlog("tpbegin: timeout=%lu", timeout);
    (void)flags;
    return 0;
}

int tpcommit(long flags)
{
    userlog("tpcommit");
    (void)flags;
    return 0;
}

int tpabort(long flags)
{
    userlog("tpabort");
    (void)flags;
    return 0;
}
