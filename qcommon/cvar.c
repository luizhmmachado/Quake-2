/*
Copyright (C) 1997-2001 Id Software, Inc.

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  

See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

*/
// cvar.c -- dynamic variable tracking

#include "qcommon.h"

cvar_t	*cvar_vars;

/*
============
Cvar_InfoValidate
============
*/
static qboolean Cvar_InfoValidate (char *s)
{
	if (strstr (s, "\\"))
		return false;
	if (strstr (s, "\""))
		return false;
	if (strstr (s, ";"))
		return false;
	return true;
}

/*
============
Cvar_FindVar
============
*/
static cvar_t *Cvar_FindVar (char *var_name)
{
	cvar_t	*var;
	
	for (var=cvar_vars ; var ; var=var->next)
		if (!strcmp (var_name, var->name))
			return var;

	return NULL;
}

/*
============
Cvar_IsNumericString

Returns true when the whole string can be parsed as a number.
============
*/
static qboolean Cvar_IsNumericString (char *s)
{
	char	*end;

	if (!s || !*s)
		return false;

	strtod (s, &end);
	if (end == s)
		return false;

	while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n')
		end++;

	return *end == 0;
}

/*
============
Cvar_ValueIsValid

Numeric cvars are validated against their default type.  Info cvars keep
their existing character restrictions as well.
============
*/
static qboolean Cvar_ValueIsValid (cvar_t *var, char *value)
{
	if (!value)
		return false;

	if (var->flags & (CVAR_USERINFO | CVAR_SERVERINFO))
	{
		if (!Cvar_InfoValidate (value))
			return false;
	}

	if (var->default_string && Cvar_IsNumericString (var->default_string))
		return Cvar_IsNumericString (value);

	return true;
}

/*
============
Cvar_ReportInvalid

Prints a clear console message whenever a value is rejected.
============
*/
static void Cvar_ReportInvalid (cvar_t *var, char *value)
{
	if (var->default_string)
		Com_Printf ("WARNING: invalid value \"%s\" for \"%s\", using default \"%s\"\n",
			value, var->name, var->default_string);
	else
		Com_Printf ("WARNING: invalid value \"%s\" for \"%s\", keeping \"%s\"\n",
			value, var->name, var->string);
}

/*
============
Cvar_SetString

Replaces a cvar value, keeping all derived fields in sync.
============
*/
static void Cvar_SetString (cvar_t *var, char *value)
{
	Z_Free (var->string);
	var->string = CopyString (value);
	var->value = atof (var->string);
	var->modified = true;

	if (var->flags & CVAR_USERINFO)
		userinfo_modified = true;
}

/*
============
Cvar_Create

Low level cvar allocation.  default_value is only set by Cvar_Get when a
cvar is actually registered by the engine/game code.
============
*/
static cvar_t *Cvar_Create (char *var_name, char *var_value, int flags, char *default_value)
{
	cvar_t	*var;

	var = Z_Malloc (sizeof(*var));
	var->name = CopyString (var_name);
	var->string = CopyString (var_value);
	var->latched_string = NULL;
	var->default_string = default_value ? CopyString (default_value) : NULL;
	var->modified = true;
	var->value = atof (var->string);
	var->flags = flags;

	// link the variable in
	var->next = cvar_vars;
	cvar_vars = var;

	return var;
}

/*
============
Cvar_VariableValue
============
*/
float Cvar_VariableValue (char *var_name)
{
	cvar_t	*var;
	
	var = Cvar_FindVar (var_name);
	if (!var)
		return 0;
	return atof (var->string);
}


/*
============
Cvar_VariableString
============
*/
char *Cvar_VariableString (char *var_name)
{
	cvar_t *var;
	
	var = Cvar_FindVar (var_name);
	if (!var)
		return "";
	return var->string;
}


/*
============
Cvar_CompleteVariable
============
*/
char *Cvar_CompleteVariable (char *partial)
{
	cvar_t		*cvar;
	int			len;
	
	len = strlen(partial);
	
	if (!len)
		return NULL;
		
	// check exact match
	for (cvar=cvar_vars ; cvar ; cvar=cvar->next)
		if (!strcmp (partial,cvar->name))
			return cvar->name;

	// check partial match
	for (cvar=cvar_vars ; cvar ; cvar=cvar->next)
		if (!strncmp (partial,cvar->name, len))
			return cvar->name;

	return NULL;
}


/*
============
Cvar_Get

If the variable already exists, the value will not be set
The flags will be or'ed in if the variable exists.
============
*/
cvar_t *Cvar_Get (char *var_name, char *var_value, int flags)
{
	cvar_t	*var;
	
	if (flags & (CVAR_USERINFO | CVAR_SERVERINFO))
	{
		if (!Cvar_InfoValidate (var_name))
		{
			Com_Printf("invalid info cvar name\n");
			return NULL;
		}
	}

	var = Cvar_FindVar (var_name);
	if (var)
	{
		var->flags |= flags;

		// A cvar may have been created by a "set" command while config.cfg
		// was being read, before the engine registered its real default.
		// Register the default now and validate the value that was loaded.
		if (var_value && !var->default_string)
		{
			var->default_string = CopyString (var_value);

			if (!Cvar_ValueIsValid (var, var->string))
			{
				Cvar_ReportInvalid (var, var->string);
				Cvar_SetString (var, var->default_string);
			}
		}

		return var;
	}

	if (!var_value)
		return NULL;

	if (flags & (CVAR_USERINFO | CVAR_SERVERINFO))
	{
		if (!Cvar_InfoValidate (var_value))
		{
			Com_Printf("invalid info cvar value\n");
			return NULL;
		}
	}

	return Cvar_Create (var_name, var_value, flags, var_value);
}

/*
============
Cvar_Set2
============
*/
cvar_t *Cvar_Set2 (char *var_name, char *value, qboolean force)
{
	cvar_t	*var;

	var = Cvar_FindVar (var_name);
	if (!var)
	{	// create it; only Cvar_Get sets a canonical default
		return Cvar_Create (var_name, value, 0, NULL);
	}

	if (!Cvar_ValueIsValid (var, value))
	{
		Cvar_ReportInvalid (var, value);
		if (!var->default_string)
			return var;
		value = var->default_string;
	}

	if (!force)
	{
		if (var->flags & CVAR_NOSET)
		{
			Com_Printf ("%s is write protected.\n", var_name);
			return var;
		}

		if (var->flags & CVAR_LATCH)
		{
			if (var->latched_string)
			{
				if (strcmp(value, var->latched_string) == 0)
					return var;
				Z_Free (var->latched_string);
			}
			else
			{
				if (strcmp(value, var->string) == 0)
					return var;
			}

			if (Com_ServerState())
			{
				Com_Printf ("%s will be changed for next game.\n", var_name);
				var->latched_string = CopyString(value);
			}
			else
			{
				var->string = CopyString(value);
				var->value = atof (var->string);
				if (!strcmp(var->name, "game"))
				{
					FS_SetGamedir (var->string);
					FS_ExecAutoexec ();
				}
			}
			return var;
		}
	}
	else
	{
		if (var->latched_string)
		{
			Z_Free (var->latched_string);
			var->latched_string = NULL;
		}
	}

	if (!strcmp(value, var->string))
		return var;		// not changed

	Cvar_SetString (var, value);

	return var;
}

/*
============
Cvar_ForceSet
============
*/
cvar_t *Cvar_ForceSet (char *var_name, char *value)
{
	return Cvar_Set2 (var_name, value, true);
}

/*
============
Cvar_Set
============
*/
cvar_t *Cvar_Set (char *var_name, char *value)
{
	return Cvar_Set2 (var_name, value, false);
}

/*
============
Cvar_FullSet
============
*/
cvar_t *Cvar_FullSet (char *var_name, char *value, int flags)
{
	cvar_t	*var;
	
	var = Cvar_FindVar (var_name);
	if (!var)
	{	// create it
		return Cvar_Get (var_name, value, flags);
	}

	if (!Cvar_ValueIsValid (var, value))
	{
		Cvar_ReportInvalid (var, value);
		if (!var->default_string)
			return var;
		value = var->default_string;
	}

	Cvar_SetString (var, value);
	var->flags = flags;

	return var;
}

/*
============
Cvar_SetValue
============
*/
void Cvar_SetValue (char *var_name, float value)
{
	char	val[32];

	if (value == (int)value)
		Com_sprintf (val, sizeof(val), "%i",(int)value);
	else
		Com_sprintf (val, sizeof(val), "%f",value);
	Cvar_Set (var_name, val);
}


/*
============
Cvar_GetLatchedVars

Any variables with latched values will now be updated
============
*/
void Cvar_GetLatchedVars (void)
{
	cvar_t	*var;

	for (var = cvar_vars ; var ; var = var->next)
	{
		if (!var->latched_string)
			continue;
		Z_Free (var->string);
		var->string = var->latched_string;
		var->latched_string = NULL;
		var->value = atof(var->string);
		if (!strcmp(var->name, "game"))
		{
			FS_SetGamedir (var->string);
			FS_ExecAutoexec ();
		}
	}
}

/*
============
Cvar_Command

Handles variable inspection and changing from the console
============
*/
qboolean Cvar_Command (void)
{
	cvar_t			*v;

// check variables
	v = Cvar_FindVar (Cmd_Argv(0));
	if (!v)
		return false;
		
// perform a variable print or set
	if (Cmd_Argc() == 1)
	{
		Com_Printf ("\"%s\" is \"%s\"\n", v->name, v->string);
		return true;
	}

	Cvar_Set (v->name, Cmd_Argv(1));
	return true;
}


/*
============
Cvar_Set_f

Allows setting and defining of arbitrary cvars from console
============
*/
void Cvar_Set_f (void)
{
	int		c;
	int		flags;

	c = Cmd_Argc();
	if (c != 3 && c != 4)
	{
		Com_Printf ("usage: set <variable> <value> [u / s]\n");
		return;
	}

	if (c == 4)
	{
		if (!strcmp(Cmd_Argv(3), "u"))
			flags = CVAR_USERINFO;
		else if (!strcmp(Cmd_Argv(3), "s"))
			flags = CVAR_SERVERINFO;
		else
		{
			Com_Printf ("flags can only be 'u' or 's'\n");
			return;
		}
		Cvar_FullSet (Cmd_Argv(1), Cmd_Argv(2), flags);
	}
	else
		Cvar_Set (Cmd_Argv(1), Cmd_Argv(2));
}


/*
============
Cvar_IsArchived

User parameters use CVAR_ARCHIVE.  Debug parameters are never persisted,
even if they accidentally carry the archive flag.
============
*/
static qboolean Cvar_IsArchived (cvar_t *var)
{
	if (var->flags & CVAR_DEBUG)
		return false;

	return (var->flags & CVAR_ARCHIVE) != 0;
}

static void Cvar_WriteArchivedVariables (FILE *f)
{
	cvar_t	*var;

	for (var = cvar_vars ; var ; var = var->next)
	{
		if (Cvar_IsArchived (var))
			fprintf (f, "set %s \"%s\"\n", var->name, var->string);
	}
}

/*
============
Cvar_WriteVariables

Appends lines containing "set variable value" for all user variables
with the archive flag set to true.
============
*/
void Cvar_WriteVariables (char *path)
{
	FILE	*f;

	f = fopen (path, "a");
	if (!f)
	{
		Com_Printf ("Couldn't write %s.\n", path);
		return;
	}

	Cvar_WriteArchivedVariables (f);
	fclose (f);
}

/*
============
Cvar_WriteConfig

Writes a complete config.cfg in one place: header, extra client data
(key bindings), and all archived user cvars.  Debug cvars are skipped.
============
*/
void Cvar_WriteConfig (char *path, Cvar_WriteExtra_f write_extra)
{
	FILE	*f;

	f = fopen (path, "w");
	if (!f)
	{
		Com_Printf ("Couldn't write %s.\n", path);
		return;
	}

	fprintf (f, "// generated by quake, do not modify\n");
	if (write_extra)
		write_extra (f);
	Cvar_WriteArchivedVariables (f);
	fclose (f);
}

/*
============
Cvar_ExecConfig

Centralized config/preset file loader used by the exec command and by
startup.  Files are inserted into the command buffer in the order they
are requested, so default.cfg can be applied before config.cfg.
============
*/
void Cvar_ExecConfig (char *filename)
{
	char	*f, *f2;
	int		len;

	len = FS_LoadFile (filename, (void **)&f);
	if (!f)
	{
		Com_Printf ("couldn't exec %s\n", filename);
		return;
	}
	Com_Printf ("execing %s\n", filename);

	// the file doesn't have a trailing 0, so we need to copy it off
	f2 = Z_Malloc(len+1);
	memcpy (f2, f, len);
	f2[len] = 0;

	Cbuf_InsertText (f2);

	Z_Free (f2);
	FS_FreeFile (f);
}

/*
============
Cvar_List_f

============
*/
void Cvar_List_f (void)
{
	cvar_t	*var;
	int		i;

	i = 0;
	for (var = cvar_vars ; var ; var = var->next, i++)
	{
		if (var->flags & CVAR_ARCHIVE)
			Com_Printf ("*");
		else
			Com_Printf (" ");
		if (var->flags & CVAR_USERINFO)
			Com_Printf ("U");
		else
			Com_Printf (" ");
		if (var->flags & CVAR_SERVERINFO)
			Com_Printf ("S");
		else
			Com_Printf (" ");
		if (var->flags & CVAR_NOSET)
			Com_Printf ("-");
		else if (var->flags & CVAR_LATCH)
			Com_Printf ("L");
		else
			Com_Printf (" ");
		if (var->flags & CVAR_DEBUG)
			Com_Printf ("D");
		else
			Com_Printf (" ");
		Com_Printf (" %s \"%s\"\n", var->name, var->string);
	}
	Com_Printf ("%i cvars\n", i);
}


qboolean userinfo_modified;


char	*Cvar_BitInfo (int bit)
{
	static char	info[MAX_INFO_STRING];
	cvar_t	*var;

	info[0] = 0;

	for (var = cvar_vars ; var ; var = var->next)
	{
		if (var->flags & bit)
			Info_SetValueForKey (info, var->name, var->string);
	}
	return info;
}

// returns an info string containing all the CVAR_USERINFO cvars
char	*Cvar_Userinfo (void)
{
	return Cvar_BitInfo (CVAR_USERINFO);
}

// returns an info string containing all the CVAR_SERVERINFO cvars
char	*Cvar_Serverinfo (void)
{
	return Cvar_BitInfo (CVAR_SERVERINFO);
}

/*
============
Cvar_Init

Reads in all archived cvars
============
*/
void Cvar_Init (void)
{
	Cmd_AddCommand ("set", Cvar_Set_f);
	Cmd_AddCommand ("cvarlist", Cvar_List_f);

}
