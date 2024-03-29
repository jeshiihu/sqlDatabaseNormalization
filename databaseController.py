import os.path
import re
import sqlite3
from schema3nf import *
from helpers import *
from equivalence import *
import copy
from copy import deepcopy
from decompInstancev2 import *

def getDBFile():
	while(1):
		dbFile = raw_input("Please enter an input database (name.db): ")
		dbFile = dbFile.strip()
		dbFile = dbFile.replace(" ", "")

		# check if file exits
		if dbFile == "-quit":
			exit()

		if not os.path.isfile(dbFile) or not re.match(".+\\.db", dbFile):
			print "Invalid filename, please try again!"
		elif (os.path.isfile(dbFile) and re.match(".+\\.db", dbFile)):
			return dbFile

def getConnectionCursor(filename):
	conn = sqlite3.connect(filename) 
	conn.text_factory = str
	c = conn.cursor()
	c.execute('PRAGMA foreign_keys=ON;')

	conn.row_factory = sqlite3.Row
	c = conn.cursor()
	return conn, c

def findClosure(conn, c):
	print "Finding Closure"
	attrSet = raw_input("Please enter attribute set (i.e. A,B): ")
	if attrSet == "-quit":
		exit()
	
	attrSet = attrSet.replace(" ", "")
	attrSet = strStripUpper(attrSet)

	fdTableName = ""
	while(1):
		fdTableName = raw_input("Please enter the FD table name: ")

		if fdTableName == "-quit":
			exit()

		if not tableExists(conn, c, fdTableName):
			print "Table does not exist, please try again!"
			continue
		else:
			break

	fdSet = getFDSet(conn, c, fdTableName);
	print attrSet + "+ = " + getClosure(getStringSet(attrSet), fdSet);

def synthesizeTo3NF(conn, c):
	print "=== Synthesizing 3NF ==="

	# returns a set of (LHS, RHS)
	minimalCover = computeMinimalCover(conn, c)
	partitionedSet = partitionSetToSameLHS(minimalCover)
	schema = formSchemaForEachUi(partitionedSet)
	newRiDict = addAdditionalSchemaIfNoSuperKey(conn, c, minimalCover)

	createTables(conn, c, schema)

	inputTableName = getInputTableName(conn, c)
	outputTableName = inputTableName.replace("Input", "Output") + "_"
	createRelationalTables(conn, c, newRiDict)

	print "=== Synthesis into 3NF complete! ==="


def decomposeToBCNF(conn, c):
	print "decomposing to BCNF"
	sqlGetRTable = '''
				SELECT name
				 FROM sqlite_master 
				 WHERE type='table' AND name LIKE 'input_%' AND name NOT LIKE 'input_fds_%';
				'''
	c.execute(sqlGetRTable)
	Rtable = c.fetchone()
	sqlGetR = '''
			select *
			from %s;
			'''
	c.execute(sqlGetR %Rtable[0])
	row = c.fetchone()
	Rsql = row.keys()
	R = ''
	for attribute in Rsql:
		R = R + attribute
	print(R)

	getTableColumnAndType(c, Rtable)

	sqlGetFTable = '''
			SELECT name 
			FROM sqlite_master 
			WHERE type='table' AND name LIKE 'input_fds_%';
			'''
	c.execute(sqlGetFTable)
	Ftable = c.fetchone()
	sqlGetF = '''
			select *
			from %s;
			'''
	c.execute(sqlGetF %Ftable[0])
	F = c.fetchall()
	print(F)

	BCNFR = []
	BCNFFD = []
	F2 = copy.copy(F)
	R2 = copy.copy(R)

	F1 = findViolatingBCNF(R2,F2)
	if (F1 == 'no violating'):
		print('already in BCNF')
		for R in R2:
			BCNFR.append(('',R))
		for FD in F2:
			BCNFFD.append(FD)
	else :
		print('Not in BCNF')
		while (1) :
			F1 = findViolatingBCNF(R2,F2)
			if (F1 == 'no violating'):
				BCNFR.append(('',R2))
				break
			if not F2:
				BCNFR.append(R2)
				break

			LHS = F1[0]
			RHS = F1[1].replace(',', '')
			R1 = LHS.replace(',','') + RHS.replace(',','')
			BCNFR.append((LHS,R1))
			BCNFFD.append(F1)
			for attribute in RHS:
				if attribute in R:
					R2 = R2.replace(attribute, '')
			F2.remove(F1)
			for FD in F2:
				index = F2.index(FD)
				FDcopy = list(FD)
				FDLHS = FDcopy[0].replace(',','') 
				FDRHS = FDcopy[1].replace(',', '')
				for RHSattribute in RHS:
					if (RHSattribute in FDLHS):
						F2.remove(FD)
						break
					if(RHSattribute in FDRHS):
						del F2[index]
						FDcopy[1] = FDcopy[1].replace(RHSattribute, '')
						if (FDcopy[1].replace(RHSattribute,'') == ''):
							break
						else:
							F2.insert(index, (FDcopy[0], FDcopy[1].replace(RHSattribute,'')))

	print('******************************************************************************************')
	print('My Rs are: ',  BCNFR)
	print('my Fds are: ', BCNFFD)
	print(findDependencyPreserving(F, BCNFFD))
	createBCNFTables(conn, c, BCNFR, BCNFFD)


def findDependencyPreserving (F, Fprime):
	if(all(FD in Fprime for FD in F)):
		return 'is dependency preserving'
	allClosures = findAllClosures(Fprime)
	allOgClosures = findAllClosures(F)
	preserved = True
	for FD in F:
		status = False
		LHSFD = FD[0].replace(',', '')
		RHSFD = FD[1].replace(',', '')
		for FDprime in allClosures:
			LHSFDprime = FDprime[0].replace(',', '')
			RHSFDprime = FDprime[1].replace(',', '')
			if((LHSFD == LHSFDprime) and (all(attribute in RHSFDprime for attribute in RHSFD))):
				status = True
				break
		if (status == False):
			preserved = False
			return 'is NOT dependency preserving'
	if (preserved == True):
		return 'is dependency preserving'

def findAllClosures(F):
	allClosures = []
	for FD in F:
		LHS = FD[0]
		enclosure = LHS.replace(',', '')
		RHS = FD[1]
		otherF = copy.copy(F)
		otherF.remove(FD)
		closure = (LHS + RHS).replace(',','')
		foundViolatingFD = False;
		while (foundViolatingFD == False):
			old = closure
			for otherFD in otherF:
				otherFDLHS = otherFD[0].replace(',', '')
				if(all(attribute in closure for attribute in otherFDLHS)):
					otherFDRHS = otherFD[1].replace(',', '')
					for addAttribute in otherFDRHS:
						for attribute in addAttribute:
							if (attribute not in closure):
								closure = closure + attribute
			if (old == closure):
				break
		allClosures.append((enclosure, closure))
	return allClosures

def findViolatingBCNF (R, F):
	for FD in F:
		LHS = FD[0]
		RHS = FD[1]
		otherF = copy.copy(F)
		otherF.remove(FD)
		closure = (LHS + RHS).replace(',','')
		foundViolatingFD = False;
		while (foundViolatingFD == False):
			old = closure
			for otherFD in otherF:
				otherFDLHS = otherFD[0].replace(',', '')
				if(all(attribute in closure for attribute in otherFDLHS)):
					otherFDRHS = otherFD[1].replace(',', '')
					for addAttribute in otherFDRHS:
						for attribute in addAttribute:
							if (attribute not in closure):
								closure = closure + attribute
			if (old == closure):
				if(all(attribute in closure for attribute in R)):
					break
				else:
					return FD
					foundViolatingFD = True
	return 'no violating'

def createBCNFFDTables(conn, c, F):
	inputFdTableName = getFDTableName(conn, c)
	baseOutputName = inputFdTableName.replace("Input", "Output") + "_"

	for FD in F:
		# create the output FDs tables
		Relation = FD[0].replace(',','') + FD[1].replace(',','')
		fdTableName = baseOutputName + ''.join(Relation)
		dropTable(conn, c, fdTableName)
		query = "CREATE TABLE " + fdTableName + " (LHS TEXT, RHS TEXT);"
		#print(query)
		c.execute(query)
		insert = [FD[0], FD[1]] #lhs rhs
		query = "INSERT INTO " + fdTableName + " VALUES (?,?)"
		c.execute(query, insert)
		conn.commit()

def createBCNFRelationalTables(conn, c, R):
	inputTableName = getInputTableName(conn, c)
	baseOutputName = inputTableName.replace("Input", "Output") + "_"
	
	c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (inputTableName, ))
	result = c.fetchone()
	tableInfo = getTableColumnAndType(c, result)

	for Relation in R:
		if (Relation[0] != ''):
			key = Relation[1]
			columns = ""
			tableName = baseOutputName + ''.join(key)
			for attr in key:
				columnType = getSpecificColumnType(tableInfo, attr)
				columns = columns + attr + " " + columnType + ', '
			primaryKey = Relation[0]
			columns = columns + "PRIMARY KEY (" + primaryKey + ")"
			columns = strStripUpper(columns)
			dropTable(conn, c, tableName)
			query = "CREATE TABLE " + tableName + "(" + columns + ");"
			c.execute(query)
			conn.commit()

		else:
			key = Relation[1]
			columns = ""
			tableName = baseOutputName + ''.join(key)
			for attr in key:
				columnType = getSpecificColumnType(tableInfo, attr)
				columns = columns + attr + " " + columnType + ', '
			columns = strStripUpper(columns)
			dropTable(conn, c, tableName)
			query = "CREATE TABLE " + tableName + "(" + columns + ");"
			c.execute(query)
			conn.commit()

	conn.commit()

def createBCNFTables(conn, c, R, F): # format is a dict
	createBCNFRelationalTables(conn, c, R)
	createBCNFFDTables(conn, c, F)


def equivalence(conn,c):
	F1names = raw_input("FD tables for F1? (comma seperated) \n")
	if F1names == "-quit":
		exit()

	F2names = raw_input("FD tables for F2? (comma seperated) \n")
	if F2names == "-quit":
		exit()

	F1names = F1names.strip().split(',')
	F2names = F2names.strip().split(',')

	print("F1NAMES",F1names)
	print("F2Names",F2names)


	F1=set()
	F2=set()


	for fdTable in F1names:
		query = "SELECT * FROM " + fdTable 
		c.execute(query)
		result = c.fetchall()
		print(result)

		for r in result:
			F1.update(result)

	for fdTable in F2names:
		query = "SELECT * FROM " + fdTable 
		c.execute(query)
		result = c.fetchall()
		print(result)

		for r in result:
			F2.update(result)
		
	print('F1',F1)
	print('F2',F2)
	print(checkEquivalence(F1,F2))


def promptForDecomposeInstance(conn, c):
	input = raw_input("Would you like to decompose the original instance into the new output tables [y/n]? ")
	input = strStripLower(input)
	if input == "-quit":
		exit()


	if input == 'y':
		decomposeInstance(conn, c)
	elif input == 'n':
		return
	else:
		print "Invalid input, please try again"
		promptForDecomposeInstance(conn, c)
		 




