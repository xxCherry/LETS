from lets import glob
from helpers import scoreHelper
from helpers import passwordHelper
import time
from helpers import logHelper as log

def cacheUserIDs():
	"""Cache userIDs in glob.userIDCache, used later with getID()."""
	data = glob.db.fetchAll("SELECT id, username FROM users WHERE allowed = 1")
	for i in data:
		glob.userIDCache[i["username"]] = i["id"]

def getID(username):
	"""
	Get username's user ID from userID cache (if cache hit)
	or from db (and cache it for other requests) if cache miss

	username -- user
	return -- user id or 0
	"""
	# Add to cache if needed
	if username not in glob.userIDCache:
		userID = glob.db.fetch("SELECT id FROM users WHERE username = %s", [username])
		if userID == None:
			return 0
		glob.userIDCache[username] = result

	# Get userID from cache
	return glob.userIDCache[username]

def getUsername(userID):
	"""
	Get userID's username

	userID -- userID
	return -- username or None
	"""
	result = glob.db.fetch("SELECT username FROM users WHERE id = %s", [userID])
	if result == None:
		return None
	return result["username"]


def exists(userID):
	"""
	Check if given userID exists

	userID -- user id to check
	"""
	return True if glob.db.fetch("SELECT id FROM users WHERE id = %s", [userID]) != None else False


def checkLogin(userID, password, ip = ""):
	"""
	Check userID's login with specified password

	userID -- user id
	password -- plain md5 password
	ip -- request IP (used to check bancho active sessions). Optional.
	return -- True or False
	"""
	# Check cached bancho session
	banchoSession = False
	if ip != "":
		banchoSession = checkBanchoSession(userID, ip)

	# Return True if there's a bancho session for this user from that ip
	if banchoSession == True:
		log.debug("Found cached bancho session")
		return True

	# Otherwise, check password
	# Get password data
	passwordData = glob.db.fetch("SELECT password_md5, salt, password_version FROM users WHERE id = %s", [userID])

	# Make sure the query returned something
	if passwordData == None:
		return False

	# Return valid/invalid based on the password version.
	if passwordData["password_version"] == 2:
		return passwordHelper.checkNewPassword(password, passwordData["password_md5"])
	if passwordData["password_version"] == 1:
		ok = passwordHelper.checkOldPassword(password, passwordData["salt"], passwordData["password_md5"])
		if not ok: return False
		newpass = passwordHelper.genBcrypt(password)
		glob.db.execute("UPDATE users SET password_md5=%s, salt='', password_version='2' WHERE id = %s", [newpass, userID])


def getRequiredScoreForLevel(level):
	"""
	Return score required to reach a level

	level -- level to reach
	return -- required score
	"""
	if level <= 100:
		if level >= 2:
			return 5000 / 3 * (4 * (level ** 3) - 3 * (level ** 2) - level) + 1.25 * (1.8 ** (level - 60))
		elif level <= 0 or level == 1:
			return 1	# Should be 0, but we get division by 0 below so set to 1
	elif level >= 101:
		return 26931190829 + 100000000000 * (level - 100)


def getLevel(totalScore):
	"""
	Return level from totalScore

	totalScore -- total score
	return -- level
	"""
	level = 1
	while True:
		# if the level is > 8000, it's probably an endless loop. terminate it.
		if level > 8000:
			return level

		# Calculate required score
		reqScore = getRequiredScoreForLevel(level)

		# Check if this is our level
		if totalScore <= reqScore:
			# Our level, return it and break
			return level - 1
		else:
			# Not our level, calculate score for next level
			level+=1

def updateLevel(userID, gameMode):
	"""
	Update level in DB for userID relative to gameMode
	"""
	if not exists(userID):
		return

	mode = scoreHelper.readableGameMode(gameMode)
	totalScore = glob.db.fetch("SELECT total_score_{m} FROM users_stats WHERE id = %s".format(m = mode), [userID])
	level = getLevel(totalScore["total_score_{m}".format(m = mode)])
	glob.db.execute("UPDATE users_stats SET level_{m} = %s WHERE id = %s".format(m = mode), [level, userID])


def calculateAccuracy(userID, gameMode):
	"""
	Calculate accuracy value for userID relative to gameMode

	userID --
	gameMode -- gameMode number
	return -- new accuracy
	"""
	# Select what to sort by
	if gameMode == 0:
		sortby = "pp"
	else:
		sortby = "accuracy"
	# Get best accuracy scores
	bestAccScores = glob.db.fetchAll("SELECT accuracy FROM scores WHERE userid = %s AND play_mode = %s AND completed = '3' ORDER BY " + sortby + " DESC LIMIT 100", [userID, gameMode])

	v = 0
	if bestAccScores != None:
		# Calculate weighted accuracy
		totalAcc = 0
		divideTotal = 0
		k = 0
		for i in bestAccScores:
			add = int( (0.95 ** k) * 100)
			totalAcc += i["accuracy"] * add
			divideTotal += add
			k += 1
			# echo "$add - $totalacc - $divideTotal\n"
		if divideTotal != 0:
			v = totalAcc / divideTotal
		else:
			v = 0
	return v


def calculatePP(userID, gameMode):
	"""
	Calculate userID's total PP for gameMode

	userID -- ID of user
	gameMode -- gameMode number
	return -- total PP
	"""
	# Get best pp scores
	bestPPScores = glob.db.fetchAll("SELECT pp FROM scores WHERE userid = %s AND play_mode = %s AND completed = '3' ORDER BY pp DESC LIMIT 100", [userID, gameMode])

	# Calculate weighted PP
	totalPP = 0
	if bestPPScores != None:
		k = 0
		for i in bestPPScores:
			new = round( round(i["pp"]) * 0.95 ** k)
			totalPP += new
			# print("{} (w {}% aka {})".format(i["pp"], 0.95 ** k * 100, new))
			k += 1

	return totalPP


def updateAccuracy(userID, gameMode):
	"""
	Update accuracy value for userID relative to gameMode in DB

	userID --
	gameMode -- gameMode number
	"""

	username = getUsername(userID)
	if username == None:
		return
	newAcc = calculateAccuracy(userID, gameMode)
	mode = scoreHelper.readableGameMode(gameMode)
	glob.db.execute("UPDATE users_stats SET avg_accuracy_{m} = %s WHERE username = %s".format(m = mode), [newAcc, username])


def updatePP(userID, gameMode):
	"""
	Update userID's pp with new value

	userID -- userID
	pp -- pp to add
	gameMode -- gameMode number
	"""
	# Make sure the user exists
	if not exists(userID):
		return

	# Get new total PP and update db
	newPP = calculatePP(userID, gameMode)
	mode = scoreHelper.readableGameMode(gameMode)
	glob.db.execute("UPDATE users_stats SET pp_{}=%s WHERE id = %s".format(mode), [newPP, userID])


def updateStats(userID, __score):
	"""
	Update stats (playcount, total score, ranked score, level bla bla)
	with data relative to a score object

	userID --
	__score -- score object
	"""

	# Make sure the user exists
	if not exists(userID):
		log.warning("User {} doesn't exist.".format(userID))
		return

	# Get gamemode for db
	mode = scoreHelper.readableGameMode(__score.gameMode)

	# Update total score and playcount
	glob.db.execute("UPDATE users_stats SET total_score_{m}=total_score_{m}+%s, playcount_{m}=playcount_{m}+1 WHERE id = %s".format(m=mode), [__score.score, userID])

	# Calculate new level and update it
	updateLevel(userID, __score.gameMode)

	# Update level, accuracy and ranked score only if we have passed the song
	if __score.passed == True:
		# Update ranked score
		glob.db.execute("UPDATE users_stats SET ranked_score_{m}=ranked_score_{m}+%s WHERE id = %s".format(m=mode), [__score.rankedScoreIncrease, userID])

		# Update accuracy
		updateAccuracy(userID, __score.gameMode)

		# Update pp
		updatePP(userID, __score.gameMode)


def getAllowed(userID):
	"""
	Get allowed status for userID

	db -- database connection
	userID -- user ID
	return -- allowed int
	"""

	result = glob.db.fetch("SELECT allowed FROM users WHERE id = %s", [userID])
	if result != None:
		return result["allowed"]
	else:
		return None

def updateLatestActivity(userID):
	"""
	Update userID's latest activity to current UNIX time

	userID --
	"""
	glob.db.execute("UPDATE users SET latest_activity = %s WHERE id = %s", [int(time.time()), userID])

def getAllowedUsers(by = "username"):
	"""
	Return a dictionary containing all allowed status for every user users

	by -- column used to identity users. Can be username or id
	return -- allowed users dictionary (key: by, value: True/False)
	"""
	# get all the allowed users in Ripple
	allowedUsersRaw = glob.db.fetchAll("SELECT {}, allowed FROM users".format(by))

	# Future array containing all the allowed users.
	allowedUsers = {}

	# Fill up the allowedUsers dictionary
	for i in allowedUsersRaw:
		allowedUsers[i[by]] = True if i["allowed"] == 1 else False

	return allowedUsers

def getRankedScore(userID, gameMode):
	"""
	Get userID's ranked score relative to gameMode

	userID -- userID
	gameMode -- int value, see gameModes
	return -- ranked score
	"""

	mode = scoreHelper.readableGameMode(gameMode)
	result = glob.db.fetch("SELECT ranked_score_{} FROM users_stats WHERE id = %s".format(mode), [userID])
	if result != None:
		return result["ranked_score_{}".format(mode)]
	else:
		return 0

def getPP(userID, gameMode):
	"""
	Get userID's PP relative to gameMode

	userID -- userID
	gameMode -- int value, see gameModes
	return -- PP
	"""

	mode = scoreHelper.readableGameMode(gameMode)
	result = glob.db.fetch("SELECT pp_{} FROM users_stats WHERE id = %s".format(mode), [userID])
	if result != None:
		return result["pp_{}".format(mode)]
	else:
		return 0

def incrementReplaysWatched(userID, gameMode):
	"""
	Increment userID's replays watched by others relative to gameMode

	userID -- user ID
	gameMode -- int value, see gameModes
	"""
	mode = scoreHelper.readableGameMode(gameMode)
	glob.db.execute("UPDATE users_stats SET replays_watched_{mode}=replays_watched_{mode}+1 WHERE id = %s".format(mode=mode), [userID])


def setAllowed(userID, allowed):
	"""
	Set userID's allowed status

	userID -- user
	allowed -- allowed status. 1: normal, 0: banned
	"""
	banDateTime = int(time.time()) if allowed == 0 else 0
	glob.db.execute("UPDATE users SET allowed = %s, ban_datetime = %s WHERE id = %s", [allowed, banDateTime, userID])

def getAqn(userID):
	"""
	Check if AQN folder was detected for userID

	userID -- user
	return -- True if hax, False if legit
	"""
	result = glob.db.fetch("SELECT aqn FROM users WHERE id = %s", [userID])
	if result != None:
		return True if int(result["aqn"]) == 1 else False
	else:
		return False

def setAqn(userID, value = 1):
	"""
	Set AQN folder status for userID

	userID -- user
	value -- new aqn value, default = 1
	"""
	glob.db.fetch("UPDATE users SET aqn = %s WHERE id = %s", [value, userID])

def botnet(userID, ip):
	"""
	Botnet the user
	"""
	glob.db.execute("""INSERT INTO ip_user (userid, ip, occurencies) VALUES (%s, %s, '1')
						ON DUPLICATE KEY UPDATE occurencies = occurencies + 1""", [userID, ip])

def checkBanchoSession(userID, ip = ""):
	"""
	Return True if there is a bancho session for userID from ip

	userID --
	ip -- optional
	return -- True/False
	"""
	if ip != "":
		result = glob.db.fetch("SELECT id FROM bancho_sessions WHERE userid = %s AND ip = %s", [userID, ip])
	else:
		result = glob.db.fetch("SELECT id FROM bancho_sessions WHERE userid = %s", [userID])

	return False if result == None else True

def is2FAEnabled(userID):
	"""Returns True if 2FA is enable for this account"""
	result = glob.db.fetch("SELECT id FROM 2fa_telegram WHERE userid = %s LIMIT 1", [userID])
	return True if result is not None else False

def check2FA(userID, ip):
	"""Returns True if this IP is untrusted"""
	if is2FAEnabled(userID) == False:
		return False

	result = glob.db.fetch("SELECT id FROM ip_user WHERE userid = %s AND ip = %s", [userID, ip])
	return True if result is None else False
