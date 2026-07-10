/*
 * atmi.h - Simulated Tuxedo ATMI (Application-to-Transaction Monitor Interface)
 *
 * Provides the Tuxedo API surface that batch processing .pc files expect.
 * In a real Tuxedo system, this is provided by <atmi.h> from $TUXDIR/include.
 */
#ifndef SIMULATED_ATMI_H
#define SIMULATED_ATMI_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* --- Tuxedo return codes --- */
#define TPSUCCESS  0
#define TPFAIL     1
#define TPEXIT     2

/* --- tpacall flags --- */
#define TPNOREPLY  0x01
#define TPNOTRAN   0x02
#define TPTRAN     0x04

/* --- Buffer types --- */
#define STRING     0
#define CARRAY     1
#define FML         2
#define VIEW        3

/* ─── FML (Field Manipulation Language) ──────────────────────────────── */
#define FML_MAX_FIELDS  128

#define FLD_STRING  0
#define FLD_INT     1
#define FLD_DOUBLE  2

typedef struct {
    int    fldid;
    int    type;
    int    occ;
    char   str_val[512];
    int    int_val;
    double dbl_val;
} FML_FIELD;

typedef struct {
    int        buftype;
    int        field_count;
    FML_FIELD  fields[FML_MAX_FIELDS];
} FML_BUF;

/* Field IDs — Input (100–199) */
#define FLD_CLIENT_CODE     100
#define FLD_RISK_DATE       101
#define FLD_SCENARIO_FLAG   102
#define FLD_CLIENT_SEGMENT  103
#define FLD_PORTFOLIO_TYPE  104
#define FLD_REQUEST_ID      105

/* Field IDs — Output (200–299) */
#define FLD_VAR_95              200
#define FLD_VAR_99              201
#define FLD_MAX_DRAWDOWN        202
#define FLD_SHARPE_RATIO        203
#define FLD_BETA_WEIGHTED       204
#define FLD_STRESS_LOSS_PCT     205
#define FLD_STRESS_LOSS_PCT_2   206
#define FLD_STRESS_LOSS_PCT_3   207
#define FLD_MARGIN_DEFICIT      208
#define FLD_CONCENTRATION_RISK  209
#define FLD_LIQUIDITY_SCORE     210
#define FLD_RISK_GRADE          211
#define FLD_ACTION_REQUIRED     212
#define FLD_TOTAL_EXPOSURE      213
#define FLD_HEDGE_EFFECTIVENESS 214
#define FLD_SECTOR_EXPOSURE_JSON 215

/* Scenario flags for BATCH_COMPREHENSIVE_RISK */
#define SF_BASIC_RISK     0x01
#define SF_STRESS_TEST    0x02
#define SF_MARGIN         0x04
#define SF_CONCENTRATION  0x08
#define SF_COMPLIANCE     0x10
#define SF_INTERNAL       0x20
#define SF_FULL_OUTPUT    0x40
#define SF_DEBUG          0x80
#define SF_DEFAULT        0x7F

/* FML API */
FML_BUF *Falloc(void);
void     Ffree(FML_BUF *fbfr);
int      Fadd(FML_BUF *fbfr, int fldid, const void *value, int len);
int      Fget(FML_BUF *fbfr, int fldid, int occ, void *value, int *len);
int      Fchg(FML_BUF *fbfr, int fldid, int occ, const void *value, int len);
int      Fldid(const char *fldname);
int      Fldno(FML_BUF *fbfr, int fldid);

/* --- TPSVCINFO: service request context --- */
typedef struct {
    char  name[32];    /* service name */
    long  flags;       /* flags */
    char  *data;       /* input buffer */
    long  len;         /* input buffer length */
    int   cd;          /* connection descriptor */
    int   appkey;      /* application key */
    long  urcode;      /* user return code */
} TPSVCINFO;

/* --- Function pointer for service dispatch --- */
typedef void (*TPSVCFUNC)(TPSVCINFO *);

/* --- Service registration table --- */
typedef struct {
    char      *svcname;
    TPSVCFUNC  func;
} SERVICE_TABLE;

/* --- Library lifecycle --- */
int  tux_init(int argc, char *argv[]);
void tux_done(void);
int  tux_run(SERVICE_TABLE *svctab);

/* --- Service communication --- */
int  tpcall(const char *svcname, char *idata, long ilen, char **odata, long *olen, long flags);
int  tpacall(const char *svcname, char *data, long len, long flags);
int  tpgetrply(int *cd, char **data, long *len, long flags);
void tpreturn(int rval, long rcode, char *data, long len, long flags);
void tpforward(const char *svcname, char *data, long len, long flags);

/* --- Logging --- */
void userlog(const char *fmt, ...);

/* --- Memory --- */
char *tpalloc(int buftype, char *subtype, long size);
void  tpfree(char *ptr);

/* --- Transaction --- */
int  tpbegin(unsigned long timeout, long flags);
int  tpcommit(long flags);
int  tpabort(long flags);

/* --- Global error --- */
extern int tperrno;
extern char *tpstrerror(int err);

#endif /* SIMULATED_ATMI_H */
