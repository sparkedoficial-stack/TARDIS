# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.

from __future__ import annotations

from cryptography.hazmat.bindings._rust import (
    ObjectIdentifier as ObjectIdentifier,
)
from cryptography.hazmat.primitives import hashes


class ExtensionOID:
    SUBJECT_DIRECTORY_ATTRIBUTES = ObjectIdentifier("REDACTED_IP")
    SUBJECT_KEY_IDENTIFIER = ObjectIdentifier("REDACTED_IP")
    KEY_USAGE = ObjectIdentifier("REDACTED_IP")
    PRIVATE_KEY_USAGE_PERIOD = ObjectIdentifier("REDACTED_IP")
    SUBJECT_ALTERNATIVE_NAME = ObjectIdentifier("REDACTED_IP")
    ISSUER_ALTERNATIVE_NAME = ObjectIdentifier("REDACTED_IP")
    BASIC_CONSTRAINTS = ObjectIdentifier("REDACTED_IP")
    NAME_CONSTRAINTS = ObjectIdentifier("REDACTED_IP")
    CRL_DISTRIBUTION_POINTS = ObjectIdentifier("REDACTED_IP")
    CERTIFICATE_POLICIES = ObjectIdentifier("REDACTED_IP")
    POLICY_MAPPINGS = ObjectIdentifier("REDACTED_IP")
    AUTHORITY_KEY_IDENTIFIER = ObjectIdentifier("REDACTED_IP")
    POLICY_CONSTRAINTS = ObjectIdentifier("REDACTED_IP")
    EXTENDED_KEY_USAGE = ObjectIdentifier("REDACTED_IP")
    FRESHEST_CRL = ObjectIdentifier("REDACTED_IP")
    INHIBIT_ANY_POLICY = ObjectIdentifier("REDACTED_IP")
    ISSUING_DISTRIBUTION_POINT = ObjectIdentifier("REDACTED_IP")
    AUTHORITY_INFORMATION_ACCESS = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")
    SUBJECT_INFORMATION_ACCESS = ObjectIdentifier("REDACTED_IP.REDACTED_IP.11")
    OCSP_NO_CHECK = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1.5")
    TLS_FEATURE = ObjectIdentifier("REDACTED_IP.REDACTED_IP.24")
    CRL_NUMBER = ObjectIdentifier("REDACTED_IP")
    DELTA_CRL_INDICATOR = ObjectIdentifier("REDACTED_IP")
    PRECERT_SIGNED_CERTIFICATE_TIMESTAMPS = ObjectIdentifier(
        "REDACTED_IP.4.1.11129.2.4.2"
    )
    PRECERT_POISON = ObjectIdentifier("REDACTED_IP.4.1.11129.2.4.3")
    SIGNED_CERTIFICATE_TIMESTAMPS = ObjectIdentifier("REDACTED_IP.4.1.11129.2.4.5")
    MS_CERTIFICATE_TEMPLATE = ObjectIdentifier("REDACTED_IP.REDACTED_IP.7")
    ADMISSIONS = ObjectIdentifier("REDACTED_IP.3.3")


class OCSPExtensionOID:
    NONCE = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1.2")
    ACCEPTABLE_RESPONSES = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1.4")


class CRLEntryExtensionOID:
    CERTIFICATE_ISSUER = ObjectIdentifier("REDACTED_IP")
    CRL_REASON = ObjectIdentifier("REDACTED_IP")
    INVALIDITY_DATE = ObjectIdentifier("REDACTED_IP")


class NameOID:
    COMMON_NAME = ObjectIdentifier("REDACTED_IP")
    COUNTRY_NAME = ObjectIdentifier("REDACTED_IP")
    LOCALITY_NAME = ObjectIdentifier("REDACTED_IP")
    STATE_OR_PROVINCE_NAME = ObjectIdentifier("REDACTED_IP")
    STREET_ADDRESS = ObjectIdentifier("REDACTED_IP")
    ORGANIZATION_IDENTIFIER = ObjectIdentifier("REDACTED_IP")
    ORGANIZATION_NAME = ObjectIdentifier("REDACTED_IP")
    ORGANIZATIONAL_UNIT_NAME = ObjectIdentifier("REDACTED_IP")
    SERIAL_NUMBER = ObjectIdentifier("REDACTED_IP")
    SURNAME = ObjectIdentifier("REDACTED_IP")
    GIVEN_NAME = ObjectIdentifier("REDACTED_IP")
    TITLE = ObjectIdentifier("REDACTED_IP")
    INITIALS = ObjectIdentifier("REDACTED_IP")
    GENERATION_QUALIFIER = ObjectIdentifier("REDACTED_IP")
    X500_UNIQUE_IDENTIFIER = ObjectIdentifier("REDACTED_IP")
    DN_QUALIFIER = ObjectIdentifier("REDACTED_IP")
    PSEUDONYM = ObjectIdentifier("REDACTED_IP")
    USER_ID = ObjectIdentifier("0.9.2342.19200300.100.1.1")
    DOMAIN_COMPONENT = ObjectIdentifier("0.9.2342.19200300.100.1.25")
    EMAIL_ADDRESS = ObjectIdentifier("1.2.840.113549.1.9.1")
    JURISDICTION_COUNTRY_NAME = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2.1.3")
    JURISDICTION_LOCALITY_NAME = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2.1.1")
    JURISDICTION_STATE_OR_PROVINCE_NAME = ObjectIdentifier(
        "REDACTED_IP.REDACTED_IP.2.1.2"
    )
    BUSINESS_CATEGORY = ObjectIdentifier("REDACTED_IP")
    POSTAL_ADDRESS = ObjectIdentifier("REDACTED_IP")
    POSTAL_CODE = ObjectIdentifier("REDACTED_IP")
    INN = ObjectIdentifier("REDACTED_IP.131.1.1")
    OGRN = ObjectIdentifier("REDACTED_IP.1")
    SNILS = ObjectIdentifier("REDACTED_IP.3")
    UNSTRUCTURED_NAME = ObjectIdentifier("1.2.840.113549.1.9.2")
    UNSIGNED = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")


class SignatureAlgorithmOID:
    RSA_WITH_MD5 = ObjectIdentifier("1.2.840.113549.1.1.4")
    RSA_WITH_SHA1 = ObjectIdentifier("1.2.840.113549.1.1.5")
    # This is an alternate OID for RSA with SHA1 that is occasionally seen
    _RSA_WITH_SHA1 = ObjectIdentifier("REDACTED_IP.2.29")
    RSA_WITH_SHA224 = ObjectIdentifier("1.2.840.113549.1.1.14")
    RSA_WITH_SHA256 = ObjectIdentifier("1.2.840.113549.1.1.11")
    RSA_WITH_SHA384 = ObjectIdentifier("1.2.840.113549.1.1.12")
    RSA_WITH_SHA512 = ObjectIdentifier("1.2.840.113549.1.1.13")
    RSA_WITH_SHA3_224 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.13")
    RSA_WITH_SHA3_256 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.14")
    RSA_WITH_SHA3_384 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.15")
    RSA_WITH_SHA3_512 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.16")
    RSASSA_PSS = ObjectIdentifier("1.2.840.113549.1.1.10")
    ECDSA_WITH_SHA1 = ObjectIdentifier("1.2.840.10045.4.1")
    ECDSA_WITH_SHA224 = ObjectIdentifier("1.2.840.10045.4.3.1")
    ECDSA_WITH_SHA256 = ObjectIdentifier("1.2.840.10045.4.3.2")
    ECDSA_WITH_SHA384 = ObjectIdentifier("1.2.840.10045.4.3.3")
    ECDSA_WITH_SHA512 = ObjectIdentifier("1.2.840.10045.4.3.4")
    ECDSA_WITH_SHA3_224 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.9")
    ECDSA_WITH_SHA3_256 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.10")
    ECDSA_WITH_SHA3_384 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.11")
    ECDSA_WITH_SHA3_512 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.12")
    DSA_WITH_SHA1 = ObjectIdentifier("1.2.840.10040.4.3")
    DSA_WITH_SHA224 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")
    DSA_WITH_SHA256 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2")
    DSA_WITH_SHA384 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.3")
    DSA_WITH_SHA512 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.4")
    ED25519 = ObjectIdentifier("REDACTED_IP")
    ED448 = ObjectIdentifier("REDACTED_IP")
    ML_DSA_44 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.17")
    ML_DSA_65 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.18")
    ML_DSA_87 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.19")
    GOSTR3411_94_WITH_3410_2001 = ObjectIdentifier("REDACTED_IP.2.3")
    GOSTR3410_2012_WITH_3411_2012_256 = ObjectIdentifier("REDACTED_IP.REDACTED_IP")
    GOSTR3410_2012_WITH_3411_2012_512 = ObjectIdentifier("REDACTED_IP.REDACTED_IP")
    UNSIGNED = ObjectIdentifier("REDACTED_IP.REDACTED_IP.36")


_SIG_OIDS_TO_HASH: dict[ObjectIdentifier, hashes.HashAlgorithm | None] = {
    SignatureAlgorithmOID.RSA_WITH_MD5: hashes.MD5(),
    SignatureAlgorithmOID.RSA_WITH_SHA1: hashes.SHA1(),
    SignatureAlgorithmOID._RSA_WITH_SHA1: hashes.SHA1(),
    SignatureAlgorithmOID.RSA_WITH_SHA224: hashes.SHA224(),
    SignatureAlgorithmOID.RSA_WITH_SHA256: hashes.SHA256(),
    SignatureAlgorithmOID.RSA_WITH_SHA384: hashes.SHA384(),
    SignatureAlgorithmOID.RSA_WITH_SHA512: hashes.SHA512(),
    SignatureAlgorithmOID.RSA_WITH_SHA3_224: hashes.SHA3_224(),
    SignatureAlgorithmOID.RSA_WITH_SHA3_256: hashes.SHA3_256(),
    SignatureAlgorithmOID.RSA_WITH_SHA3_384: hashes.SHA3_384(),
    SignatureAlgorithmOID.RSA_WITH_SHA3_512: hashes.SHA3_512(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA1: hashes.SHA1(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA224: hashes.SHA224(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA256: hashes.SHA256(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA384: hashes.SHA384(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA512: hashes.SHA512(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA3_224: hashes.SHA3_224(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA3_256: hashes.SHA3_256(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA3_384: hashes.SHA3_384(),
    SignatureAlgorithmOID.ECDSA_WITH_SHA3_512: hashes.SHA3_512(),
    SignatureAlgorithmOID.DSA_WITH_SHA1: hashes.SHA1(),
    SignatureAlgorithmOID.DSA_WITH_SHA224: hashes.SHA224(),
    SignatureAlgorithmOID.DSA_WITH_SHA256: hashes.SHA256(),
    SignatureAlgorithmOID.ED25519: None,
    SignatureAlgorithmOID.ED448: None,
    SignatureAlgorithmOID.ML_DSA_44: None,
    SignatureAlgorithmOID.ML_DSA_65: None,
    SignatureAlgorithmOID.ML_DSA_87: None,
    SignatureAlgorithmOID.GOSTR3411_94_WITH_3410_2001: None,
    SignatureAlgorithmOID.GOSTR3410_2012_WITH_3411_2012_256: None,
    SignatureAlgorithmOID.GOSTR3410_2012_WITH_3411_2012_512: None,
    SignatureAlgorithmOID.UNSIGNED: None,
}


class HashAlgorithmOID:
    SHA1 = ObjectIdentifier("REDACTED_IP.2.26")
    SHA224 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.4")
    SHA256 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")
    SHA384 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2")
    SHA512 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.3")
    SHA3_224 = ObjectIdentifier("REDACTED_IP.4.1.37476.REDACTED_IP.7.224")
    SHA3_256 = ObjectIdentifier("REDACTED_IP.4.1.37476.REDACTED_IP.7.256")
    SHA3_384 = ObjectIdentifier("REDACTED_IP.4.1.37476.REDACTED_IP.7.384")
    SHA3_512 = ObjectIdentifier("REDACTED_IP.4.1.37476.REDACTED_IP.7.512")
    SHA3_224_NIST = ObjectIdentifier("REDACTED_IP.REDACTED_IP.7")
    SHA3_256_NIST = ObjectIdentifier("REDACTED_IP.REDACTED_IP.8")
    SHA3_384_NIST = ObjectIdentifier("REDACTED_IP.REDACTED_IP.9")
    SHA3_512_NIST = ObjectIdentifier("REDACTED_IP.REDACTED_IP.10")


class PublicKeyAlgorithmOID:
    DSA = ObjectIdentifier("1.2.840.10040.4.1")
    EC_PUBLIC_KEY = ObjectIdentifier("1.2.840.10045.2.1")
    RSAES_PKCS1_v1_5 = ObjectIdentifier("1.2.840.113549.1.1.1")
    RSASSA_PSS = ObjectIdentifier("1.2.840.113549.1.1.10")
    X25519 = ObjectIdentifier("REDACTED_IP")
    X448 = ObjectIdentifier("REDACTED_IP")
    ED25519 = ObjectIdentifier("REDACTED_IP")
    ED448 = ObjectIdentifier("REDACTED_IP")
    ML_DSA_44 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.17")
    ML_DSA_65 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.18")
    ML_DSA_87 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.19")
    ML_KEM_768 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2")
    ML_KEM_1024 = ObjectIdentifier("REDACTED_IP.REDACTED_IP.3")


class ExtendedKeyUsageOID:
    SERVER_AUTH = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")
    CLIENT_AUTH = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2")
    CODE_SIGNING = ObjectIdentifier("REDACTED_IP.REDACTED_IP.3")
    EMAIL_PROTECTION = ObjectIdentifier("REDACTED_IP.REDACTED_IP.4")
    TIME_STAMPING = ObjectIdentifier("REDACTED_IP.REDACTED_IP.8")
    OCSP_SIGNING = ObjectIdentifier("REDACTED_IP.REDACTED_IP.9")
    ANY_EXTENDED_KEY_USAGE = ObjectIdentifier("REDACTED_IP.0")
    SMARTCARD_LOGON = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2.2")
    KERBEROS_PKINIT_KDC = ObjectIdentifier("REDACTED_IP.REDACTED_IP")
    IPSEC_IKE = ObjectIdentifier("REDACTED_IP.REDACTED_IP.17")
    BUNDLE_SECURITY = ObjectIdentifier("REDACTED_IP.REDACTED_IP.35")
    CERTIFICATE_TRANSPARENCY = ObjectIdentifier("REDACTED_IP.4.1.11129.2.4.4")


class OtherNameFormOID:
    PERMANENT_IDENTIFIER = ObjectIdentifier("REDACTED_IP.REDACTED_IP.3")
    HW_MODULE_NAME = ObjectIdentifier("REDACTED_IP.REDACTED_IP.4")
    DNS_SRV = ObjectIdentifier("REDACTED_IP.REDACTED_IP.7")
    NAI_REALM = ObjectIdentifier("REDACTED_IP.REDACTED_IP.8")
    SMTP_UTF8_MAILBOX = ObjectIdentifier("REDACTED_IP.REDACTED_IP.9")
    ACP_NODE_NAME = ObjectIdentifier("REDACTED_IP.REDACTED_IP.10")
    BUNDLE_EID = ObjectIdentifier("REDACTED_IP.REDACTED_IP.11")


class AuthorityInformationAccessOID:
    CA_ISSUERS = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2")
    OCSP = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")


class SubjectInformationAccessOID:
    CA_REPOSITORY = ObjectIdentifier("REDACTED_IP.REDACTED_IP.5")


class CertificatePoliciesOID:
    CPS_QUALIFIER = ObjectIdentifier("REDACTED_IP.REDACTED_IP.1")
    CPS_USER_NOTICE = ObjectIdentifier("REDACTED_IP.REDACTED_IP.2")
    ANY_POLICY = ObjectIdentifier("REDACTED_IP.0")


class AttributeOID:
    CHALLENGE_PASSWORD = ObjectIdentifier("1.2.840.113549.1.9.7")
    UNSTRUCTURED_NAME = ObjectIdentifier("1.2.840.113549.1.9.2")


_OID_NAMES = {
    NameOID.COMMON_NAME: "commonName",
    NameOID.COUNTRY_NAME: "countryName",
    NameOID.LOCALITY_NAME: "localityName",
    NameOID.STATE_OR_PROVINCE_NAME: "stateOrProvinceName",
    NameOID.STREET_ADDRESS: "streetAddress",
    NameOID.ORGANIZATION_NAME: "organizationName",
    NameOID.ORGANIZATIONAL_UNIT_NAME: "organizationalUnitName",
    NameOID.SERIAL_NUMBER: "serialNumber",
    NameOID.SURNAME: "surname",
    NameOID.GIVEN_NAME: "givenName",
    NameOID.TITLE: "title",
    NameOID.GENERATION_QUALIFIER: "generationQualifier",
    NameOID.X500_UNIQUE_IDENTIFIER: "x500UniqueIdentifier",
    NameOID.DN_QUALIFIER: "dnQualifier",
    NameOID.PSEUDONYM: "pseudonym",
    NameOID.USER_ID: "userID",
    NameOID.DOMAIN_COMPONENT: "domainComponent",
    NameOID.EMAIL_ADDRESS: "emailAddress",
    NameOID.JURISDICTION_COUNTRY_NAME: "jurisdictionCountryName",
    NameOID.JURISDICTION_LOCALITY_NAME: "jurisdictionLocalityName",
    NameOID.JURISDICTION_STATE_OR_PROVINCE_NAME: (
        "jurisdictionStateOrProvinceName"
    ),
    NameOID.BUSINESS_CATEGORY: "businessCategory",
    NameOID.POSTAL_ADDRESS: "postalAddress",
    NameOID.POSTAL_CODE: "postalCode",
    NameOID.INN: "INN",
    NameOID.OGRN: "OGRN",
    NameOID.SNILS: "SNILS",
    NameOID.UNSTRUCTURED_NAME: "unstructuredName",
    SignatureAlgorithmOID.RSA_WITH_MD5: "md5WithRSAEncryption",
    SignatureAlgorithmOID.RSA_WITH_SHA1: "sha1WithRSAEncryption",
    SignatureAlgorithmOID.RSA_WITH_SHA224: "sha224WithRSAEncryption",
    SignatureAlgorithmOID.RSA_WITH_SHA256: "sha256WithRSAEncryption",
    SignatureAlgorithmOID.RSA_WITH_SHA384: "sha384WithRSAEncryption",
    SignatureAlgorithmOID.RSA_WITH_SHA512: "sha512WithRSAEncryption",
    SignatureAlgorithmOID.RSASSA_PSS: "rsassaPss",
    SignatureAlgorithmOID.ECDSA_WITH_SHA1: "ecdsa-with-SHA1",
    SignatureAlgorithmOID.ECDSA_WITH_SHA224: "ecdsa-with-SHA224",
    SignatureAlgorithmOID.ECDSA_WITH_SHA256: "ecdsa-with-SHA256",
    SignatureAlgorithmOID.ECDSA_WITH_SHA384: "ecdsa-with-SHA384",
    SignatureAlgorithmOID.ECDSA_WITH_SHA512: "ecdsa-with-SHA512",
    SignatureAlgorithmOID.DSA_WITH_SHA1: "dsa-with-sha1",
    SignatureAlgorithmOID.DSA_WITH_SHA224: "dsa-with-sha224",
    SignatureAlgorithmOID.DSA_WITH_SHA256: "dsa-with-sha256",
    SignatureAlgorithmOID.ED25519: "ed25519",
    SignatureAlgorithmOID.ED448: "ed448",
    SignatureAlgorithmOID.ML_DSA_44: "ML-DSA-44",
    SignatureAlgorithmOID.ML_DSA_65: "ML-DSA-65",
    SignatureAlgorithmOID.ML_DSA_87: "ML-DSA-87",
    SignatureAlgorithmOID.GOSTR3411_94_WITH_3410_2001: (
        "GOST R 34.11-94 with GOST R 34.10-2001"
    ),
    SignatureAlgorithmOID.GOSTR3410_2012_WITH_3411_2012_256: (
        "GOST R 34.10-2012 with GOST R 34.11-2012 (256 bit)"
    ),
    SignatureAlgorithmOID.GOSTR3410_2012_WITH_3411_2012_512: (
        "GOST R 34.10-2012 with GOST R 34.11-2012 (512 bit)"
    ),
    HashAlgorithmOID.SHA1: "sha1",
    HashAlgorithmOID.SHA224: "sha224",
    HashAlgorithmOID.SHA256: "sha256",
    HashAlgorithmOID.SHA384: "sha384",
    HashAlgorithmOID.SHA512: "sha512",
    HashAlgorithmOID.SHA3_224: "sha3_224",
    HashAlgorithmOID.SHA3_256: "sha3_256",
    HashAlgorithmOID.SHA3_384: "sha3_384",
    HashAlgorithmOID.SHA3_512: "sha3_512",
    HashAlgorithmOID.SHA3_224_NIST: "sha3_224",
    HashAlgorithmOID.SHA3_256_NIST: "sha3_256",
    HashAlgorithmOID.SHA3_384_NIST: "sha3_384",
    HashAlgorithmOID.SHA3_512_NIST: "sha3_512",
    PublicKeyAlgorithmOID.DSA: "dsaEncryption",
    PublicKeyAlgorithmOID.EC_PUBLIC_KEY: "id-ecPublicKey",
    PublicKeyAlgorithmOID.RSAES_PKCS1_v1_5: "rsaEncryption",
    PublicKeyAlgorithmOID.X25519: "X25519",
    PublicKeyAlgorithmOID.X448: "X448",
    ExtendedKeyUsageOID.SERVER_AUTH: "serverAuth",
    ExtendedKeyUsageOID.CLIENT_AUTH: "clientAuth",
    ExtendedKeyUsageOID.CODE_SIGNING: "codeSigning",
    ExtendedKeyUsageOID.EMAIL_PROTECTION: "emailProtection",
    ExtendedKeyUsageOID.TIME_STAMPING: "timeStamping",
    ExtendedKeyUsageOID.OCSP_SIGNING: "OCSPSigning",
    ExtendedKeyUsageOID.SMARTCARD_LOGON: "msSmartcardLogin",
    ExtendedKeyUsageOID.KERBEROS_PKINIT_KDC: "pkInitKDC",
    ExtensionOID.SUBJECT_DIRECTORY_ATTRIBUTES: "subjectDirectoryAttributes",
    ExtensionOID.SUBJECT_KEY_IDENTIFIER: "subjectKeyIdentifier",
    ExtensionOID.KEY_USAGE: "keyUsage",
    ExtensionOID.PRIVATE_KEY_USAGE_PERIOD: "privateKeyUsagePeriod",
    ExtensionOID.SUBJECT_ALTERNATIVE_NAME: "subjectAltName",
    ExtensionOID.ISSUER_ALTERNATIVE_NAME: "issuerAltName",
    ExtensionOID.BASIC_CONSTRAINTS: "basicConstraints",
    ExtensionOID.PRECERT_SIGNED_CERTIFICATE_TIMESTAMPS: (
        "signedCertificateTimestampList"
    ),
    ExtensionOID.SIGNED_CERTIFICATE_TIMESTAMPS: (
        "signedCertificateTimestampList"
    ),
    ExtensionOID.PRECERT_POISON: "ctPoison",
    ExtensionOID.MS_CERTIFICATE_TEMPLATE: "msCertificateTemplate",
    ExtensionOID.ADMISSIONS: "Admissions",
    CRLEntryExtensionOID.CRL_REASON: "cRLReason",
    CRLEntryExtensionOID.INVALIDITY_DATE: "invalidityDate",
    CRLEntryExtensionOID.CERTIFICATE_ISSUER: "certificateIssuer",
    ExtensionOID.NAME_CONSTRAINTS: "nameConstraints",
    ExtensionOID.CRL_DISTRIBUTION_POINTS: "cRLDistributionPoints",
    ExtensionOID.CERTIFICATE_POLICIES: "certificatePolicies",
    ExtensionOID.POLICY_MAPPINGS: "policyMappings",
    ExtensionOID.AUTHORITY_KEY_IDENTIFIER: "authorityKeyIdentifier",
    ExtensionOID.POLICY_CONSTRAINTS: "policyConstraints",
    ExtensionOID.EXTENDED_KEY_USAGE: "extendedKeyUsage",
    ExtensionOID.FRESHEST_CRL: "freshestCRL",
    ExtensionOID.INHIBIT_ANY_POLICY: "inhibitAnyPolicy",
    ExtensionOID.ISSUING_DISTRIBUTION_POINT: "issuingDistributionPoint",
    ExtensionOID.AUTHORITY_INFORMATION_ACCESS: "authorityInfoAccess",
    ExtensionOID.SUBJECT_INFORMATION_ACCESS: "subjectInfoAccess",
    ExtensionOID.OCSP_NO_CHECK: "OCSPNoCheck",
    ExtensionOID.CRL_NUMBER: "cRLNumber",
    ExtensionOID.DELTA_CRL_INDICATOR: "deltaCRLIndicator",
    ExtensionOID.TLS_FEATURE: "TLSFeature",
    AuthorityInformationAccessOID.OCSP: "OCSP",
    AuthorityInformationAccessOID.CA_ISSUERS: "caIssuers",
    SubjectInformationAccessOID.CA_REPOSITORY: "caRepository",
    CertificatePoliciesOID.CPS_QUALIFIER: "id-qt-cps",
    CertificatePoliciesOID.CPS_USER_NOTICE: "id-qt-unotice",
    OCSPExtensionOID.NONCE: "OCSPNonce",
    AttributeOID.CHALLENGE_PASSWORD: "challengePassword",
}
