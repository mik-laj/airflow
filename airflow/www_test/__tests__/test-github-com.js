const puppeteer = require('puppeteer');

describe('jest-image-snapshot usage with an image received from puppeteer', () => {
  let browser;
  let page;
  let navigationPromise;

  async function login(page) {
    await page.waitForSelector('#username')
    await page.type('#username', 'root');
    await page.waitForSelector('#password')
    await page.type('#password', 'root');
    await page.click('input[type=submit]');

    await navigationPromise;
  }

  beforeAll(async () => {
    browser = await puppeteer.launch();
    page = await browser.newPage();

    await page.goto("http://localhost:8009");

    await page.setViewport({ width: 1280, height: 800 })
    
    navigationPromise = page.waitForNavigation()

    await login(page);

  })

  function testPage(pageUri) {
    it(`page: ${pageUri}`, async () => {
      await page.goto(pageUri);

      await navigationPromise;

      expect(await page.screenshot()).toMatchImageSnapshot();

    }, 3000);
  };

  [
    "http://localhost:8009/home",
    "http://localhost:8009/tree?dag_id=example_bash_operator",
    "http://localhost:8009/graph?dag_id=example_bash_operator&root=",
    "http://localhost:8009/tree?dag_id=example_bash_operator&root=",
    "http://localhost:8009/duration?dag_id=example_bash_operator&days=30&root=",
    "http://localhost:8009/tries?dag_id=example_bash_operator&days=30&root=",
    "http://localhost:8009/landing_times?dag_id=example_bash_operator&days=30&root=",
    "http://localhost:8009/gantt?dag_id=example_bash_operator&root=",
    "http://localhost:8009/dag_details?dag_id=example_bash_operator",
    "http://localhost:8009/code?dag_id=example_bash_operator&root=",
    "http://localhost:8009/users/list/",
    "http://localhost:8009/roles/list/",
    "http://localhost:8009/userstatschartview/chart/",
    "http://localhost:8009/permissions/list/",
    "http://localhost:8009/permissionviews/list/",
    "http://localhost:8009/dagrun/list/",
    "http://localhost:8009/job/list/",
    "http://localhost:8009/log/list/",
    "http://localhost:8009/slamiss/list/",
    "http://localhost:8009/taskinstance/list/",
    "http://localhost:8009/connection/list/",
    "http://localhost:8009/pool/list/",
    "http://localhost:8009/variable/list/",
    "http://localhost:8009/xcom/list/",
    "http://localhost:8009/version",
    "http://localhost:8009/versigggon",
  ].forEach(testPage);

  const sleep = time => new Promise(resolve => setTimeout(resolve, time)) 

  it(`task instance:`, async () => {
    await page.goto("http://localhost:8009/taskinstance/list/");
    await navigationPromise;

    await page.click('table > tbody > tr:nth-child(1) > td:nth-child(4) a:nth-child(1)');

    await navigationPromise;

    expect(await page.screenshot()).toMatchImageSnapshot();

  }, 3000);
  
  Array.from({length: 4}, (d, i) => i + 1).forEach(i => {
    it(`task instance: tab - ${i}`, async () => {
      await page.goto("http://localhost:8009/taskinstance/list/");
      await navigationPromise;
  
      await page.click('table > tbody > tr:nth-child(1) > td:nth-child(4) a:nth-child(1)');
  
      await navigationPromise;
      // console.log(page.url())
      // console.log(await  page.$('body').$eval('.nav-pills', node => node.innerText))
      await page.waitForSelector(`h4 + .nav-pills li:nth-child(${i}) a`)
      await page.click(`h4 + .nav-pills li:nth-child(${i}) a`);
  
      await navigationPromise;
  
      expect(await page.screenshot()).toMatchImageSnapshot();
  
    }, 3000);
  })

  afterAll(async () => {
    await browser.close();
  })

});
