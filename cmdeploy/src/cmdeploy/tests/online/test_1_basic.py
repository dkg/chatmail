import smtplib

import pytest

from cmdeploy import remote_funcs
from cmdeploy.sshexec import SSHExec


class TestSSHExecutor:
    @pytest.fixture
    def sshexec(self, sshdomain):
        return SSHExec(sshdomain, remote_funcs)

    def test_ls(self, sshexec):
        out = sshexec(remote_funcs.shell, command="ls")
        out2 = sshexec(remote_funcs.shell, command="ls")
        assert out == out2

    def test_perform_initial(self, sshexec, maildomain):
        res = sshexec(remote_funcs.perform_initial_checks, mail_domain=maildomain)
        assert res["ipv4"] or res["ipv6"]


def test_remote(remote, imap_or_smtp):
    lineproducer = remote.iter_output(imap_or_smtp.logcmd)
    imap_or_smtp.connect()
    assert imap_or_smtp.name in next(lineproducer)


def test_use_two_chatmailservers(cmfactory, maildomain2):
    ac1 = cmfactory.new_online_configuring_account(cache=False)
    cmfactory.switch_maildomain(maildomain2)
    ac2 = cmfactory.new_online_configuring_account(cache=False)
    cmfactory.bring_accounts_online()
    cmfactory.get_accepted_chat(ac1, ac2)
    domain1 = ac1.get_config("addr").split("@")[1]
    domain2 = ac2.get_config("addr").split("@")[1]
    assert domain1 != domain2


@pytest.mark.parametrize("forgeaddr", ["internal", "someone@example.org"])
def test_reject_forged_from(cmsetup, maildata, gencreds, lp, forgeaddr):
    user1, user3 = cmsetup.gen_users(2)

    lp.sec("send encrypted message with forged from")
    print("envelope_from", user1.addr)
    if forgeaddr == "internal":
        addr_to_forge = cmsetup.gen_users(1)[0].addr
    else:
        addr_to_forge = "someone@example.org"

    print("message to inject:")
    msg = maildata("encrypted.eml", from_addr=addr_to_forge, to_addr=user3.addr)
    msg = msg.as_string()
    for line in msg.split("\n")[:4]:
        print(f"   {line}")

    lp.sec("Send forged mail and check remote postfix lmtp processing result")
    with pytest.raises(smtplib.SMTPException) as e:
        user1.smtp.sendmail(from_addr=user1.addr, to_addrs=[user3.addr], msg=msg)
    assert "500" in str(e.value)


def test_authenticated_from(cmsetup, maildata):
    """Test that envelope FROM must be the same as login."""
    user1, user2, user3 = cmsetup.gen_users(3)

    msg = maildata("encrypted.eml", from_addr=user2.addr, to_addr=user3.addr)
    with pytest.raises(smtplib.SMTPException) as e:
        user1.smtp.sendmail(
            from_addr=user2.addr, to_addrs=[user3.addr], msg=msg.as_string()
        )
    assert e.value.recipients[user3.addr][0] == 553


@pytest.mark.parametrize("from_addr", ["fake@example.org", "fake@testrun.org"])
def test_reject_missing_dkim(cmsetup, maildata, from_addr):
    """Test that emails with missing or wrong DMARC, DKIM, and SPF entries are rejected."""
    recipient = cmsetup.gen_users(1)[0]
    msg = maildata("plain.eml", from_addr=from_addr, to_addr=recipient.addr).as_string()
    with smtplib.SMTP(cmsetup.maildomain, 25) as s:
        with pytest.raises(smtplib.SMTPDataError, match="No valid DKIM signature"):
            s.sendmail(from_addr=from_addr, to_addrs=recipient.addr, msg=msg)


@pytest.mark.slow
def test_exceed_rate_limit(cmsetup, gencreds, maildata, chatmail_config):
    """Test that the per-account send-mail limit is exceeded."""
    user1, user2 = cmsetup.gen_users(2)
    mail = maildata(
        "encrypted.eml", from_addr=user1.addr, to_addr=user2.addr
    ).as_string()
    for i in range(chatmail_config.max_user_send_per_minute + 5):
        print("Sending mail", str(i))
        try:
            user1.smtp.sendmail(user1.addr, [user2.addr], mail)
        except smtplib.SMTPException as e:
            if i < chatmail_config.max_user_send_per_minute:
                pytest.fail(f"rate limit was exceeded too early with msg {i}")
            outcome = e.recipients[user2.addr]
            assert outcome[0] == 450
            assert b"4.7.1: Too much mail from" in outcome[1]
            return
    pytest.fail("Rate limit was not exceeded")


@pytest.mark.slow
def test_expunged(remote, chatmail_config):
    outdated_days = int(chatmail_config.delete_mails_after) + 1
    find_cmds = [
        f"find {chatmail_config.mailboxes_dir} -path '*/cur/*' -mtime +{outdated_days} -type f",
        f"find {chatmail_config.mailboxes_dir} -path '*/.*/cur/*' -mtime +{outdated_days} -type f",
        f"find {chatmail_config.mailboxes_dir} -path '*/new/*' -mtime +{outdated_days} -type f",
        f"find {chatmail_config.mailboxes_dir} -path '*/.*/new/*' -mtime +{outdated_days} -type f",
        f"find {chatmail_config.mailboxes_dir} -path '*/tmp/*' -mtime +{outdated_days} -type f",
        f"find {chatmail_config.mailboxes_dir} -path '*/.*/tmp/*' -mtime +{outdated_days} -type f",
    ]
    for cmd in find_cmds:
        for line in remote.iter_output(cmd):
            assert not line
