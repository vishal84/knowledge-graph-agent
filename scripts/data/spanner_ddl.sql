-- ==========================================
-- 1. NODE TABLES
-- ==========================================

-- Comprehensive Person Node
CREATE TABLE Person (
    partyId STRING(MAX) NOT NULL, -- Canonical Enterprise ID
    employeeId STRING(MAX),       -- HR System ID (e.g., Workday)
    microsoftId STRING(MAX),
    enterpriseGuid STRING(MAX),   -- Generic Global Unique Identifier

    -- Name & Bio
    formattedName STRING(MAX),
    preferredFirstName STRING(MAX),
    lastName STRING(MAX),
    businessTitle STRING(MAX),
    globalGradeName STRING(MAX),
    bioSummary STRING(MAX),
    professionalInterestStatement STRING(MAX),

    -- Contact & Communication
    cloudEmailAddress STRING(MAX),
    phoneNumber STRING(MAX),

    -- Employment & Contract
    employmentStatusName STRING(MAX),
    contractTypeName STRING(MAX),
    hireDate STRING(8),
    weeklyWorkingHours FLOAT64,
    workPercentage FLOAT64,
    waysofworking STRING(MAX),
    onshoreOffshoreIndicator STRING(MAX),
    legalEntityName STRING(MAX),

    -- Organization & Hierarchy
    costCenter STRING(MAX),
    costCenterDescription STRING(MAX),
    globalLoSL1Name STRING(MAX),
    globalNetworkCompetencyName STRING(MAX),
    jobFamilyGroupName STRING(MAX),
    jobFamilyName STRING(MAX),
    jobProfileCode STRING(MAX),
    jobProfileDescription STRING(MAX),
    industryCode STRING(MAX),
    industryName STRING(MAX),

    -- Geography
    countryCode STRING(3),
    location STRING(MAX),
    officeLocation STRING(MAX),
    officeLocationCommonName STRING(MAX),
    officeLocationL2Description STRING(MAX),
    officeLocationCode STRING(MAX),
    state STRING(MAX),
    accelerationCenterIdentifier STRING(MAX),
    accelerationCenterIndicator STRING(MAX),

    -- Line of Service Hierarchy Tiers
    localLoSL1 STRING(MAX),
    localLoSL2 STRING(MAX),
    localLoSL3 STRING(MAX),
    localLoSL4 STRING(MAX),
    localLoSL5 STRING(MAX),

    -- Metadata & Complex Preferences
    lastModified TIMESTAMP,

    -- Flattened from personTravelRelocationInterest JSON array
    longTermRelocationFlag BOOL,
    shortTermRelocationFlag BOOL,
    travelInterestFlag BOOL,
    travelPercent FLOAT64,

    -- Resolved "Ghost" Properties from Ontology
    orgHierarchyDescription STRING(MAX),
    currentAreaOfFocus STRING(MAX)

) PRIMARY KEY (partyId);

-- Normalized Skill Entity
CREATE TABLE Skill (
    skillCode STRING(MAX) NOT NULL,
    skillName STRING(MAX),
    skillTypeCode STRING(MAX),
    skillTypeName STRING(MAX)
) PRIMARY KEY (skillCode);

-- External Work History Entity
CREATE TABLE Company (
    companyName STRING(MAX) NOT NULL
) PRIMARY KEY (companyName);

-- Educational Background Entity
CREATE TABLE Institution (
    institutionName STRING(MAX) NOT NULL
) PRIMARY KEY (institutionName);

-- Language Entity
CREATE TABLE Language (
    languageCode STRING(MAX) NOT NULL,
    languageName STRING(MAX)
) PRIMARY KEY (languageCode);

-- Professional Certification Entity
CREATE TABLE Certification (
    certId STRING(MAX) NOT NULL,
    certName STRING(MAX),
    certTypeName STRING(MAX)
) PRIMARY KEY (certId);


-- ==========================================
-- 2. EDGE TABLES
-- ==========================================

-- Mapping Skills (Acquired, Desired, and Top Skills)
CREATE TABLE HasSkill (
    partyId STRING(MAX) NOT NULL,
    skillCode STRING(MAX) NOT NULL,
    isTopSkill BOOL,
    isDesiredSkill BOOL,
    skillLevel STRING(MAX),
    CONSTRAINT fk_person_skill FOREIGN KEY (partyId) REFERENCES Person (partyId),
    CONSTRAINT fk_skill_ref FOREIGN KEY (skillCode) REFERENCES Skill (skillCode)
) PRIMARY KEY (partyId, skillCode);

-- Mapping Career History (from personExperiences JSON)
CREATE TABLE WorkedAt (
    partyId STRING(MAX) NOT NULL,
    companyName STRING(MAX) NOT NULL,
    jobTitle STRING(MAX),
    startDate STRING(MAX) NOT NULL,
    endDate STRING(MAX),
    location STRING(MAX),
    experienceDescription STRING(MAX),
    CONSTRAINT fk_person_exp FOREIGN KEY (partyId) REFERENCES Person (partyId),
    CONSTRAINT fk_company_ref FOREIGN KEY (companyName) REFERENCES Company (companyName)
) PRIMARY KEY (partyId, companyName, startDate);

-- Mapping Internal Professional Networks (Reporting & Support)
CREATE TABLE ProfessionalConnection (
    subjectId STRING(MAX) NOT NULL,
    relatedPersonId STRING(MAX) NOT NULL,
    connectionType STRING(MAX) NOT NULL, -- 'CAREER_COACH', 'MANAGER', 'EA', 'TC', 'DL', 'RL'
    isPrimary BOOL,             -- Differentiates between Primary EA and Secondary EA
    CONSTRAINT fk_subject_person FOREIGN KEY (subjectId) REFERENCES Person (partyId),
    CONSTRAINT fk_related_person FOREIGN KEY (relatedPersonId) REFERENCES Person (partyId)
) PRIMARY KEY (subjectId, relatedPersonId, connectionType);

-- Mapping Linguistic Proficiency (from personLanguages JSON)
CREATE TABLE Speaks (
    partyId STRING(MAX) NOT NULL,
    languageCode STRING(MAX) NOT NULL,
    abilityTypeName STRING(MAX) NOT NULL,
    proficiencyLevel STRING(MAX),
    lastAssessedDate TIMESTAMP,
    CONSTRAINT fk_person_lang FOREIGN KEY (partyId) REFERENCES Person (partyId),
    CONSTRAINT fk_lang_ref FOREIGN KEY (languageCode) REFERENCES Language (languageCode)
) PRIMARY KEY (partyId, languageCode, abilityTypeName);

-- Mapping Education History (from education JSON)
CREATE TABLE AlumnusOf (
    partyId STRING(MAX) NOT NULL,
    institutionName STRING(MAX) NOT NULL,
    degreeName STRING(MAX) NOT NULL,
    completionDate STRING(MAX),
    startDate STRING(MAX),
    CONSTRAINT fk_person_edu FOREIGN KEY (partyId) REFERENCES Person (partyId),
    CONSTRAINT fk_inst_ref FOREIGN KEY (institutionName) REFERENCES Institution (institutionName)
) PRIMARY KEY (partyId, institutionName, degreeName);

-- Mapping Recognition & Achievers Activity
CREATE TABLE Recognized (
    nominatorId STRING(MAX) NOT NULL,
    nomineeId STRING(MAX) NOT NULL,
    nominationId STRING(MAX) NOT NULL,
    dateNominated TIMESTAMP,
    reason STRING(MAX),
    criteria STRING(MAX),
    pointsAwarded INT64,
    spotBonusAmount FLOAT64,
    CONSTRAINT fk_nom_from FOREIGN KEY (nominatorId) REFERENCES Person (partyId),
    CONSTRAINT fk_nom_to FOREIGN KEY (nomineeId) REFERENCES Person (partyId)
) PRIMARY KEY (nominatorId, nomineeId, nominationId);

-- Mapping Certifications
CREATE TABLE HasCertification (
    partyId STRING(MAX) NOT NULL,
    certId STRING(MAX) NOT NULL,
    issueDate STRING(MAX),
    expirationDate STRING(MAX),
    CONSTRAINT fk_person_cert FOREIGN KEY (partyId) REFERENCES Person (partyId),
    CONSTRAINT fk_cert_ref FOREIGN KEY (certId) REFERENCES Certification (certId)
) PRIMARY KEY (partyId, certId);


-- ==========================================
-- 3. THE PROPERTY GRAPH
-- ==========================================
CREATE PROPERTY GRAPH TeamAgentGraph
  NODE TABLES (
    Person,
    Skill,
    Company,
    Institution,
    Language,
    Certification
  )
  EDGE TABLES (
    HasSkill
      SOURCE KEY (partyId) REFERENCES Person (partyId)
      DESTINATION KEY (skillCode) REFERENCES Skill (skillCode)
      LABEL HAS_SKILL,
    WorkedAt
      SOURCE KEY (partyId) REFERENCES Person (partyId)
      DESTINATION KEY (companyName) REFERENCES Company (companyName)
      LABEL PREVIOUSLY_WORKED_AT,
    ProfessionalConnection
      SOURCE KEY (subjectId) REFERENCES Person (partyId)
      DESTINATION KEY (relatedPersonId) REFERENCES Person (partyId)
      LABEL CONNECTED_TO,
    Speaks
      SOURCE KEY (partyId) REFERENCES Person (partyId)
      DESTINATION KEY (languageCode) REFERENCES Language (languageCode)
      LABEL SPEAKS,
    AlumnusOf
      SOURCE KEY (partyId) REFERENCES Person (partyId)
      DESTINATION KEY (institutionName) REFERENCES Institution (institutionName)
      LABEL ALUMNUS_OF,
    Recognized
      SOURCE KEY (nominatorId) REFERENCES Person (partyId)
      DESTINATION KEY (nomineeId) REFERENCES Person (partyId)
      LABEL RECOGNIZED,
    HasCertification
      SOURCE KEY (partyId) REFERENCES Person (partyId)
      DESTINATION KEY (certId) REFERENCES Certification (certId)
      LABEL HAS_CERTIFICATION
  );