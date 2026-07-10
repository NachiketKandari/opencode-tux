/*
 * userlog.h - Simulated Tuxedo userlog
 *
 * Provides userlog() which writes to stderr with timestamps.
 * Declaration only — implementation in tuxlib.c.
 */
#ifndef SIMULATED_USERLOG_H
#define SIMULATED_USERLOG_H

#include <stdio.h>

void userlog(const char *fmt, ...);

#endif /* SIMULATED_USERLOG_H */
