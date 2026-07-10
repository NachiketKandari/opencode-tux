/*
 * sqlca.c - Simulated SQL Communication Area implementation
 */
#include <string.h>
#include "sqlca.h"

SQLCA sqlca;

void sqlca_init(void)
{
    memset(&sqlca, 0, sizeof(sqlca));
    strncpy(sqlca.sqlcaid, "SQLCA  ", 8);
    sqlca.sqlcabc = sizeof(SQLCA);
    sqlca.sqlcode = 0;
}

void sqlca_set_error(int sql_code, const char *msg)
{
    sqlca.sqlcode = sql_code;
    sqlca.sqlerrm.sqlerrml = (unsigned short)strlen(msg);
    if (sqlca.sqlerrm.sqlerrml > 255) sqlca.sqlerrm.sqlerrml = 255;
    strncpy(sqlca.sqlerrm.sqlerrmc, msg, 255);
    sqlca.sqlerrm.sqlerrmc[255] = '\0';
    sqlca.sqlerrd[2] = 0;
}

void sqlca_set_success(int row_count)
{
    sqlca.sqlcode = 0;
    sqlca.sqlerrd[2] = row_count;
    sqlca.sqlerrm.sqlerrml = 0;
    sqlca.sqlerrm.sqlerrmc[0] = '\0';
}
